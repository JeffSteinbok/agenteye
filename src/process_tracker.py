"""
Process and window tracker for Copilot CLI sessions.
Uses pywin32 to map running sessions to terminal windows and focus them.
Also detects session state (waiting/working), yolo mode, and MCP servers.
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime

from .constants import (
    EVENT_STALENESS_THRESHOLD,
    EVENT_TAIL_BUFFER,
    MACOS_APP_NAMES,
    MACOS_FALLBACK_TERMINALS,
    MAX_ANCESTRY_DEPTH,
    MAX_DIAGNOSTICS_CHAIN,
    MAX_UNIX_PARENT_DEPTH,
    OSASCRIPT_TIMEOUT,
    OUTPUT_TAIL_BUFFER,
    POWERSHELL_TIMEOUT,
    PROCESS_MATCH_TOLERANCE,
    PS_TIMEOUT,
    RUNNING_CACHE_TTL,
    SESSION_STATE_DIR,
    TERMINAL_NAMES,
    UNIX_TERMINAL_SUBSTRINGS,
)
from .models import BackgroundTask, EventData, ProcessInfo, RunningCache, SessionState

logger = logging.getLogger(__name__)

EVENTS_DIR = SESSION_STATE_DIR

# Tool names that indicate "waiting for user input"
WAITING_TOOLS = frozenset({"ask_user", "ask_permission"})

# ---------------------------------------------------------------------------
# Caching layer
# ---------------------------------------------------------------------------
# TTL cache for get_running_sessions() — avoids repeated WMI/ps subprocess calls
_running_cache = RunningCache()
_running_lock = threading.Lock()

# Permanent cache for inactive session event data (mcp_servers, tool_counts,
# context, intent). Active sessions are re-read each poll; inactive ones are
# cached forever since their events.jsonl won't change.
_event_data_cache: dict[str, EventData] = {}

# Cache of parsed session.start/session.resume timestamps per events.jsonl file,
# keyed by file path -> (mtime, size, [datetimes]). Lets us skip re-parsing the
# (potentially huge) event logs of unchanged sessions on every poll. Guarded by
# _running_lock, since it is only touched from the get_running_sessions() path.
_lifecycle_cache: dict[str, tuple[float, int, list[datetime]]] = {}


def _read_recent_events(session_id, count=10):
    """Read the last N events from a session's events.jsonl."""
    events_file = os.path.join(EVENTS_DIR, session_id, "events.jsonl")
    if not os.path.exists(events_file):
        return []
    try:
        with open(events_file, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_from = max(0, size - EVENT_TAIL_BUFFER)
            f.seek(read_from)
            chunk = f.read().decode("utf-8", errors="replace")
        raw_lines = [ln.strip() for ln in chunk.split("\n") if ln.strip()]
        # When seeking mid-file, the first line is likely truncated — discard it
        if read_from > 0 and raw_lines:
            raw_lines = raw_lines[1:]
        events = []
        for line in raw_lines[-count:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed event line in %s", session_id)
        return events
    except Exception as e:
        logger.debug("Error reading events for %s: %s", session_id, e)
        return []


def _get_session_state(session_id) -> SessionState:
    """
    Determine session state from events.jsonl.
    Returns a SessionState dict with state, waiting_context, and bg_tasks.
    """
    events = _read_recent_events(session_id, 30)
    if not events:
        return SessionState(state="unknown", waiting_context="", bg_tasks=0, bg_task_list=[])

    # Count running subagents from full file and extract task details
    events_file = os.path.join(EVENTS_DIR, session_id, "events.jsonl")
    bg = 0
    bg_task_list: list[BackgroundTask] = []
    try:
        with open(events_file, encoding="utf-8", errors="replace") as f:
            # Track started/completed subagents by toolCallId
            started: dict[str, BackgroundTask] = {}
            for line in f:
                if '"subagent.started"' in line:
                    try:
                        evt = json.loads(line)
                        data = evt.get("data", {})
                        tcid = data.get("toolCallId", "")
                        if tcid:
                            started[tcid] = BackgroundTask(
                                agent_name=data.get("agentDisplayName")
                                or data.get("agentName", ""),
                                description=data.get("agentDescription", ""),
                            )
                    except Exception:
                        pass
                elif '"subagent.completed"' in line:
                    try:
                        evt = json.loads(line)
                        tcid = evt.get("data", {}).get("toolCallId", "")
                        started.pop(tcid, None)
                    except Exception:
                        pass
            bg = len(started)
            bg_task_list = list(started.values())
    except Exception as e:
        logger.debug("Error counting subagents for %s: %s", session_id, e)

    # Track pending tool calls from recent events
    pending_tools = {}  # toolCallId -> event data
    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {})
        if etype == "tool.execution_start":
            tcid = data.get("toolCallId", "")
            if tcid:
                pending_tools[tcid] = data
        elif etype == "tool.execution_complete":
            tcid = data.get("toolCallId", "")
            pending_tools.pop(tcid, None)

    # Check pending tools: ask_user/ask_permission → waiting, anything else → working
    has_pending_work = False
    for _tcid, data in pending_tools.items():
        tool = data.get("toolName", "")
        if tool in WAITING_TOOLS:
            args = data.get("arguments", {})
            question = args.get("question", "")
            choices = args.get("choices", [])
            ctx = question
            if choices:
                ctx += " [" + " / ".join(choices[:4]) + "]"
            return SessionState(
                state="waiting", waiting_context=ctx, bg_tasks=bg, bg_task_list=bg_task_list
            )
        if tool != "report_intent":
            has_pending_work = True

    # If any non-trivial tools are still running, check if events are stale
    if has_pending_work:
        # Check timestamp of last event — if >60s old, events are likely buffered
        last_ts = events[-1].get("timestamp", "")
        if last_ts:
            try:
                evt_time = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                age = (datetime.now(UTC) - evt_time).total_seconds()
                if age > EVENT_STALENESS_THRESHOLD:
                    return SessionState(
                        state="waiting",
                        waiting_context="Session likely waiting for input",
                        bg_tasks=bg,
                        bg_task_list=bg_task_list,
                    )
            except (ValueError, TypeError):
                pass
        return SessionState(
            state="working", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )

    # Fall back to last event type
    last = events[-1]
    etype = last.get("type", "")
    data = last.get("data", {})

    if etype == "assistant.turn_end":
        return SessionState(
            state="idle",
            waiting_context="Session idle \u2014 waiting for user message",
            bg_tasks=bg,
            bg_task_list=bg_task_list,
        )
    if etype == "tool.execution_start":
        tool = data.get("toolName", "")
        if tool in WAITING_TOOLS:
            args = data.get("arguments", {})
            return SessionState(
                state="waiting",
                waiting_context=args.get("question", ""),
                bg_tasks=bg,
                bg_task_list=bg_task_list,
            )
        return SessionState(
            state="working", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    if etype == "subagent.started":
        return SessionState(
            state="working", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    if etype in (
        "tool.execution_complete",
        "subagent.completed",
        "assistant.turn_start",
        "assistant.message",
    ):
        return SessionState(
            state="thinking", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    if etype == "user.message":
        return SessionState(
            state="thinking", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    return SessionState(state="unknown", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list)


def _parse_mcp_servers(cmdline):
    """Extract MCP server names from --additional-mcp-config flag."""
    match = re.search(r"--additional-mcp-config\s+@?([^\s]+)", cmdline)
    if not match:
        return []
    config_path = match.group(1).strip('"').strip("'")
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        servers = data.get("mcpServers", {})
        return list(servers.keys())
    except Exception as e:
        logger.debug("Error parsing MCP config %s: %s", config_path, e)
        return []


def _parse_iso_timestamp(ts_str):
    """Parse an ISO 8601 timestamp."""
    return datetime.fromisoformat(ts_str)


def _parse_lifecycle_timestamps(events_file: str) -> list[datetime]:
    """Parse session.start/session.resume timestamps from one events.jsonl.

    Uses a cheap substring pre-filter so ``json.loads`` is only run on the
    handful of lifecycle lines rather than every event in the log (event logs
    are dominated by tool/message events and can be many megabytes).
    """
    timestamps: list[datetime] = []
    try:
        with open(events_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Skip non-lifecycle lines without paying for JSON parsing.
                if "session.start" not in line and "session.resume" not in line:
                    continue
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if evt.get("type") not in ("session.start", "session.resume"):
                    continue
                ts = evt.get("timestamp", "")
                if not ts:
                    continue
                try:
                    timestamps.append(_parse_iso_timestamp(ts))
                except (ValueError, TypeError, AttributeError):
                    continue
    except OSError as e:
        logger.debug("Error reading lifecycle events from %s: %s", events_file, e)
    return timestamps


def _build_lifecycle_index() -> dict[str, list[datetime]]:
    """Map each session ID to its parsed lifecycle event timestamps.

    Scans every session's events.jsonl once and caches the result per file
    (keyed by mtime+size), so unchanged sessions are never re-parsed on later
    polls — only new or actively written logs are read again. Building this
    index once per process scan avoids re-walking thousands of session files
    for every unmatched process.
    """
    index: dict[str, list[datetime]] = {}
    if not os.path.isdir(EVENTS_DIR):
        return index
    try:
        sids = os.listdir(EVENTS_DIR)
    except OSError:
        return index
    for sid in sids:
        events_file = os.path.join(EVENTS_DIR, sid, "events.jsonl")
        try:
            st = os.stat(events_file)
        except OSError:
            continue
        cached = _lifecycle_cache.get(events_file)
        if cached is not None and cached[0] == st.st_mtime and cached[1] == st.st_size:
            timestamps = cached[2]
        else:
            timestamps = _parse_lifecycle_timestamps(events_file)
            _lifecycle_cache[events_file] = (st.st_mtime, st.st_size, timestamps)
        if timestamps:
            index[sid] = timestamps
    return index


def _match_process_to_session(creation_date_str, index=None):
    """Match a copilot.exe process (without --resume) to a session by creation time.

    Compares the process creation time to the session lifecycle timestamps found
    in events.jsonl. This includes both ``session.start`` and ``session.resume``
    because resumed sessions may no longer expose ``--resume <id>`` in the live
    process command line. Returns the session ID with the closest match within
    the configured tolerance window.

    ``index`` is an optional prebuilt ``{session_id: [datetimes]}`` map (see
    :func:`_build_lifecycle_index`). Pass it when matching many processes in a
    loop so the session logs are only scanned once; it is built on demand when
    omitted.
    """
    try:
        proc_time = _parse_iso_timestamp(creation_date_str)
    except (ValueError, TypeError, AttributeError):
        return None

    if index is None:
        index = _build_lifecycle_index()

    best_sid = None
    best_delta = PROCESS_MATCH_TOLERANCE

    for sid, timestamps in index.items():
        for evt_time in timestamps:
            delta = abs((proc_time - evt_time).total_seconds())
            if delta <= best_delta:
                best_delta = delta
                best_sid = sid

    return best_sid


def _get_running_sessions_windows() -> dict[str, ProcessInfo]:
    """Find running copilot.exe processes on Windows via PowerShell/WMI."""
    # Get all processes once, then walk ancestry in Python
    ps_script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine,"
        "@{N='CreatedUTC';E={$_.CreationDate.ToUniversalTime().ToString('o')}} | "
        "ConvertTo-Json -Depth 2"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=POWERSHELL_TIMEOUT,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.debug("Failed to parse PowerShell output: %s", e)
        return {}
    if isinstance(data, dict):
        data = [data]

    # Build a PID -> proc lookup for ancestry walking
    pid_map: dict = {p.get("ProcessId"): p for p in data if p.get("ProcessId")}

    def _find_terminal(start_pid: int) -> tuple:
        """Walk ancestors to find the nearest known terminal process."""
        visited = set()
        pid = start_pid
        for _ in range(MAX_ANCESTRY_DEPTH):
            proc = pid_map.get(pid)
            if not proc:
                break
            name = (proc.get("Name") or "").lower()
            if name in TERMINAL_NAMES:
                return proc.get("ProcessId", 0), proc.get("Name", "")
            ppid = proc.get("ParentProcessId", 0)
            if ppid == 0 or ppid in visited:
                break
            visited.add(pid)
            pid = ppid
        return 0, ""

    copilot_procs = [p for p in data if (p.get("Name") or "").lower() == "copilot.exe"]

    sessions: dict[str, ProcessInfo] = {}
    unmatched = []  # processes without --resume that need timestamp matching

    for proc in copilot_procs:
        cmd = proc.get("CommandLine", "")
        terminal_pid, terminal_name = _find_terminal(proc.get("ParentProcessId", 0))
        # Detect if launched via agency (parent is agency.exe)
        parent = pid_map.get(proc.get("ParentProcessId", 0))
        is_agency = (parent.get("Name") or "").lower() == "agency.exe" if parent else False
        proc_info = ProcessInfo(
            pid=proc.get("ProcessId", 0),
            parent_pid=proc.get("ParentProcessId", 0),
            terminal_pid=terminal_pid,
            terminal_name=terminal_name,
            cmdline=cmd,
            yolo="--yolo" in cmd,
            agency=is_agency,
            mcp_servers=_parse_mcp_servers(cmd),
        )

        if "--resume" in cmd:
            parts = cmd.split("--resume")
            if len(parts) > 1:
                sid = parts[1].strip().lstrip("=").split()[0].strip('"').strip("'")
                sessions[sid] = proc_info
        else:
            # No --resume flag — try to match by creation time
            unmatched.append((proc, proc_info))

    # Match non-resume processes to sessions by creation timestamp. Build the
    # lifecycle index once and reuse it for every unmatched process.
    lifecycle_index = _build_lifecycle_index() if unmatched else {}
    for proc, proc_info in unmatched:
        created = proc.get("CreatedUTC", "")
        sid = _match_process_to_session(created, lifecycle_index)
        if sid:
            # Prefer this over a previously unmatched entry, but don't clobber --resume matches
            if sid not in sessions or "--resume" not in sessions[sid].cmdline:
                sessions[sid] = proc_info

    return sessions


def build_unix_process_map() -> dict[int, tuple[int, str]]:
    """Return a ``{pid: (ppid, comm)}`` map of all processes via one ps call.

    Walking the process tree by spawning ``ps -p <pid>`` once per ancestor is
    O(matched processes * depth) subprocess spawns, which costs seconds when
    many Copilot/Claude processes are running. Building this map up front lets
    callers walk the tree in memory instead, turning that into a single ps call.
    """
    proc_map: dict[int, tuple[int, str]] = {}
    try:
        result = subprocess.run(
            ["ps", "axo", "pid=,ppid=,comm="],
            capture_output=True,
            text=True,
            timeout=PS_TIMEOUT,
            check=False,
        )
    except Exception as e:
        logger.debug("Error building process map: %s", e)
        return proc_map
    if result.returncode != 0 or not result.stdout.strip():
        return proc_map
    for line in result.stdout.strip().split("\n"):
        # comm may contain spaces (full path on macOS) — keep it as the remainder
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except (ValueError, IndexError):
            continue
        proc_map[pid] = (ppid, parts[2])
    return proc_map


def find_terminal_via_map(
    ppid: int, proc_map: dict[int, tuple[int, str]], max_depth: int
) -> tuple[int, str]:
    """Walk up the process tree in memory to find the controlling terminal.

    Returns ``(terminal_pid, terminal_name)``, or ``(0, "")`` if none is found
    within ``max_depth`` ancestors.
    """
    cur_ppid = ppid
    for _ in range(max_depth):
        entry = proc_map.get(cur_ppid)
        if entry is None:
            break
        next_ppid, comm = entry
        if any(t in comm.lower() for t in UNIX_TERMINAL_SUBSTRINGS):
            return cur_ppid, comm
        cur_ppid = next_ppid
    return 0, ""


def _get_running_sessions_unix() -> dict[str, ProcessInfo]:
    """Find running copilot processes on macOS/Linux via ps."""
    result = subprocess.run(
        ["ps", "axo", "pid,ppid,lstart,command"],
        capture_output=True,
        text=True,
        timeout=PS_TIMEOUT,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    # Single ps call to build the full process tree; walked in memory below.
    proc_map = build_unix_process_map()

    sessions: dict[str, ProcessInfo] = {}
    # Built lazily on the first non-resume process, then reused for the rest so
    # the session logs are scanned at most once per call.
    lifecycle_index: dict[str, list[datetime]] | None = None
    for line in result.stdout.strip().split("\n")[1:]:
        line = line.strip()
        # Match copilot binary (copilot or copilot.exe, or node ... copilot)
        if "copilot" not in line.lower():
            continue
        parts_line = line.split(None, 7)  # pid ppid lstart(5 fields) command
        if len(parts_line) < 8:
            continue
        try:
            pid = int(parts_line[0])
            ppid = int(parts_line[1])
        except (ValueError, IndexError):
            continue
        # lstart is like "Mon Feb 23 20:56:31 2026" (5 tokens)
        lstart_str = " ".join(parts_line[2:7])
        cmd = parts_line[7]

        # Walk up process tree (in memory) to find terminal PID
        terminal_pid, terminal_name = find_terminal_via_map(ppid, proc_map, MAX_UNIX_PARENT_DEPTH)

        # Detect if launched via agency (check parent command)
        parent_entry = proc_map.get(ppid)
        is_agency = bool(parent_entry and parent_entry[1].lower().endswith("agency"))

        proc_info = ProcessInfo(
            pid=pid,
            parent_pid=ppid,
            terminal_pid=terminal_pid,
            terminal_name=terminal_name,
            cmdline=cmd,
            yolo="--yolo" in cmd,
            agency=is_agency,
            mcp_servers=_parse_mcp_servers(cmd),
        )

        if "--resume" in cmd:
            # Extract session ID from --resume <session_id>
            resume_parts = cmd.split("--resume")
            if len(resume_parts) >= 2:
                sid = resume_parts[1].strip().split()[0].strip('"').strip("'")
                if sid:
                    sessions[sid] = proc_info
                    continue
        # No --resume or couldn't extract session ID — try timestamp matching
        try:
            proc_time = datetime.strptime(lstart_str, "%a %b %d %H:%M:%S %Y")
            proc_time = proc_time.astimezone(UTC)
            if lifecycle_index is None:
                lifecycle_index = _build_lifecycle_index()
            sid = _match_process_to_session(proc_time.isoformat(), lifecycle_index)
            if sid and sid not in sessions:
                sessions[sid] = proc_info
        except Exception as e:
            logger.debug("Error matching process to session by timestamp: %s", e)

    return sessions


def _get_session_match_candidates(session_id: str) -> list[str]:
    """Return a list of lowercase strings to try matching against WT tab titles.

    Ordered from most-current to least-current:
    1. Intent from events.jsonl (updated in real-time by the CLI)
    2. Summary from session-store DB (may lag behind)
    """
    candidates: list[str] = []
    # Intent is the most current signal — the CLI updates the tab title to this
    try:
        ed = _read_event_data(session_id)
        if ed.intent:
            candidates.append(ed.intent.lower())
    except Exception:
        pass
    summary = _get_session_summary(session_id)
    if summary:
        low = summary.lower()
        if low not in candidates:
            candidates.append(low)
    return candidates


def _populate_window_titles(sessions: dict[str, ProcessInfo]):
    """Populate window_title and terminal_hwnd for WT sessions via UIA.

    Scans all WT windows once, builds a map of tab titles per window, then
    matches each session using multiple candidate strings (intent, summary).
    Runs within the cache-refresh cycle so the cost is amortised.
    """
    Application = _get_pywinauto_app()
    if Application is None:
        return

    try:
        import win32gui
        import win32process

        # Collect terminal PIDs used by sessions
        wt_pids = {
            info.terminal_pid
            for info in sessions.values()
            if info.terminal_name.lower() in ("windowsterminal.exe", "wt.exe") and info.terminal_pid
        }
        if not wt_pids:
            return

        # Enumerate all WT windows
        wt_hwnds: list[int] = []

        def enum_cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid in wt_pids and win32gui.GetWindowText(hwnd):
                    wt_hwnds.append(hwnd)
            return True

        win32gui.EnumWindows(enum_cb, None)

        # Build map: (lowercase tab title, original title, hwnd)
        tab_entries: list[tuple[str, str, int]] = []
        for hwnd in wt_hwnds:
            try:
                app = Application(backend="uia").connect(handle=hwnd)
                win = app.window(handle=hwnd)
                for tab in win.descendants(control_type="TabItem"):
                    title = tab.window_text()
                    if title:
                        tab_entries.append((title.lower(), title, hwnd))
            except Exception:
                continue

        if not tab_entries:
            return

        # Match each session against tab titles using multiple candidates
        for sid, info in sessions.items():
            if info.terminal_name.lower() not in ("windowsterminal.exe", "wt.exe"):
                continue
            candidates = _get_session_match_candidates(sid)
            if not candidates:
                continue
            for candidate in candidates:
                matched = False
                for lower_title, original_title, hwnd in tab_entries:
                    if candidate in lower_title:
                        info.window_title = original_title
                        info.terminal_hwnd = hwnd
                        matched = True
                        break
                if matched:
                    break
    except Exception as e:
        logger.debug("Error populating window titles: %s", e)


def get_running_sessions() -> dict[str, ProcessInfo]:
    """
    Find running copilot processes and extract session info.
    Returns dict: {session_id: ProcessInfo}
    Uses a TTL cache to avoid repeated expensive WMI/ps subprocess calls.
    Lock is held across the entire operation so concurrent requests wait
    for the first one rather than each spawning their own subprocess.
    """
    with _running_lock:
        now = time.monotonic()
        if now - _running_cache.time < RUNNING_CACHE_TTL and _running_cache.data:
            return _running_cache.data
        try:
            if sys.platform == "win32":
                sessions = _get_running_sessions_windows()
            else:
                sessions = _get_running_sessions_unix()
            # Enrich each session with state info
            for sid, info in sessions.items():
                ss = _get_session_state(sid)
                info.state = ss["state"]
                info.waiting_context = ss["waiting_context"]
                info.bg_tasks = ss["bg_tasks"]
                info.bg_task_list = ss["bg_task_list"]

            # On Windows, populate window_title from WT tab titles (via UIA)
            if sys.platform == "win32":
                _populate_window_titles(sessions)
            _running_cache.data = sessions
            _running_cache.time = time.monotonic()
            return sessions
        except Exception as e:
            print(f"[process_tracker] Error scanning processes: {e}")
            logger.warning("Error scanning processes: %s", e)
            return _running_cache.data


def _read_event_data(session_id) -> EventData:
    """
    Read mcp_servers, tool_counts, context (cwd/branch/repo), and intent
    from a session's events.jsonl.  Returns an EventData dataclass.
    """
    result = EventData()
    events_file = os.path.join(EVENTS_DIR, session_id, "events.jsonl")
    if not os.path.exists(events_file):
        return result

    try:
        mcp_found = False
        last_intent = ""
        tool_count = 0
        sub_count = 0
        with open(events_file, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Fast string pre-checks to avoid JSON parsing every line
                if '"session.start"' in line or '"session.resume"' in line:
                    try:
                        evt = json.loads(line)
                        ctx = evt.get("data", {}).get("context", {})
                        # Always overwrite so the latest resume context wins
                        if ctx.get("cwd"):
                            result.cwd = ctx["cwd"]
                        if ctx.get("branch"):
                            result.branch = ctx["branch"]
                        if ctx.get("repository"):
                            result.repository = ctx["repository"]
                    except json.JSONDecodeError:
                        pass
                    continue

                if not mcp_found and ('"infoType":"mcp"' in line or '"infoType": "mcp"' in line):
                    try:
                        evt = json.loads(line)
                        msg = evt.get("data", {}).get("message", "")
                        if "Configured MCP servers:" in msg:
                            names = msg.split("Configured MCP servers:")[-1].strip()
                            result.mcp_servers = [n.strip() for n in names.split(",") if n.strip()]
                        elif "GitHub MCP Server" in msg:
                            result.mcp_servers = ["github"]
                        elif msg:
                            result.mcp_servers = [msg]
                        mcp_found = True
                    except json.JSONDecodeError:
                        pass
                    continue

                if '"report_intent"' in line and '"tool.execution_start"' in line:
                    try:
                        evt = json.loads(line)
                        args = evt.get("data", {}).get("arguments", {})
                        if isinstance(args, str):
                            args = json.loads(args)
                        intent = args.get("intent", "")
                        if intent:
                            last_intent = intent
                    except (json.JSONDecodeError, TypeError):
                        pass
                    continue

                # Counting — lightweight string checks, no JSON needed
                if '"tool.execution_complete"' in line:
                    tool_count += 1
                if '"subagent.completed"' in line:
                    sub_count += 1

        result.tool_calls = tool_count
        result.subagent_runs = sub_count
        result.intent = last_intent
    except Exception as e:
        logger.debug("Error reading event data for %s: %s", session_id, e)

    return result


def _get_live_branch(cwd: str) -> str:
    """Read the current git branch directly from .git/HEAD (no subprocess)."""
    if not cwd:
        return ""
    try:
        head = os.path.join(cwd, ".git", "HEAD")
        if not os.path.exists(head):
            # Walk up to find the git root (handles worktrees pointing to main .git)
            parts = cwd.replace("\\", "/").split("/")
            for i in range(len(parts) - 1, 0, -1):
                candidate = "/".join(parts[:i]) + "/.git/HEAD"
                if os.path.exists(candidate):
                    head = candidate
                    break
        with open(head, encoding="utf-8") as f:
            line = f.read().strip()
        if line.startswith("ref: refs/heads/"):
            return line[len("ref: refs/heads/") :]
    except Exception as e:
        logger.debug("Error reading git HEAD for %s: %s", cwd, e)
    return ""


def get_session_event_data(session_id, is_running=False) -> EventData:
    """
    Get cached event data for a session.
    Active sessions are always re-read; inactive sessions use permanent cache.
    """
    if not is_running and session_id in _event_data_cache:
        return _event_data_cache[session_id]

    data = _read_event_data(session_id)

    # For running sessions, refresh branch from live .git/HEAD
    if is_running and data.cwd:
        live = _get_live_branch(data.cwd)
        if live:
            data.branch = live

    # Cache permanently for inactive sessions
    if not is_running:
        _event_data_cache[session_id] = data

    return data


def get_session_mcp_servers(session_id):
    """Extract MCP server names from a session's events.jsonl (works for past sessions)."""
    return get_session_event_data(session_id).mcp_servers


def get_recent_output(session_id, max_lines=10):
    """
    Extract the last N lines of meaningful tool output from events.jsonl.
    Keeps only the output from the *last* tool completion event (intentional).
    """
    events_file = os.path.join(EVENTS_DIR, session_id, "events.jsonl")
    if not os.path.exists(events_file):
        return []
    try:
        output_lines: list[str] = []
        with open(events_file, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_from = max(0, size - OUTPUT_TAIL_BUFFER)
            f.seek(read_from)
            chunk = f.read().decode("utf-8", errors="replace")

        for raw in chunk.split("\n"):
            raw = raw.strip()
            if not raw or "tool.execution_complete" not in raw:
                continue
            try:
                event = json.loads(raw)
                if event.get("type") != "tool.execution_complete":
                    continue
                content = event.get("data", {}).get("result", {}).get("content", "")
                if not content or len(content) < 5 or content.strip() == "Intent logged":
                    continue
                # Intentionally replace: we want the last tool's output only
                output_lines = content.strip().split("\n")
            except json.JSONDecodeError:
                continue

        return output_lines[-max_lines:] if output_lines else []
    except Exception as e:
        logger.debug("Error reading recent output for %s: %s", session_id, e)
        return []


def get_session_tool_counts(session_id):
    """Count tool calls and subagent runs for a session."""
    data = get_session_event_data(session_id)
    return data.tool_calls, data.subagent_runs


def _snapshot_process_tree() -> dict[int, tuple[int, str]]:
    """Get PID -> (parent_pid, exe_name) map using a single kernel32 snapshot.

    Uses CreateToolhelp32Snapshot which completes in ~1ms — orders of magnitude
    faster than spawning PowerShell subprocesses for each ancestor.
    """
    import ctypes
    import ctypes.wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    # windll is Windows-only; type: ignore keeps mypy happy on Linux
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    INVALID_HANDLE = ctypes.wintypes.HANDLE(-1).value
    if snapshot == INVALID_HANDLE:
        return {}

    pe = PROCESSENTRY32()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
    pid_map: dict[int, tuple[int, str]] = {}
    try:
        if kernel32.Process32First(snapshot, ctypes.byref(pe)):
            while True:
                pid_map[pe.th32ProcessID] = (
                    pe.th32ParentProcessID,
                    pe.szExeFile.decode(errors="replace"),
                )
                if not kernel32.Process32Next(snapshot, ctypes.byref(pe)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)
    return pid_map


def _build_diagnostics(copilot_pid, terminal_pid, terminal_name):
    """Build diagnostics string using a single process snapshot (no subprocesses)."""
    pid_map = _snapshot_process_tree()
    chain = []
    pid = copilot_pid
    visited: set[int] = set()
    for _ in range(MAX_DIAGNOSTICS_CHAIN):
        if pid in visited or pid not in pid_map:
            break
        visited.add(pid)
        ppid, name = pid_map[pid]
        chain.append(f"  PID {pid} {name}")
        pid = ppid
    tree = "\n".join(chain)
    return (
        f"copilot PID={copilot_pid}, terminal_pid={terminal_pid} "
        f"({terminal_name})\nProcess tree:\n{tree}"
    )


_pywinauto_app_cls = None  # cached pywinauto.Application class


def _get_pywinauto_app():
    """Return the pywinauto Application class, caching the import."""
    global _pywinauto_app_cls
    if _pywinauto_app_cls is None:
        try:
            from pywinauto.application import Application

            _pywinauto_app_cls = Application
        except ImportError:
            return None
    return _pywinauto_app_cls


# Pre-warm pywinauto import in a background thread to avoid first-call latency
if sys.platform == "win32":
    threading.Thread(target=_get_pywinauto_app, daemon=True).start()


def _get_session_summary(session_id: str) -> str:
    """Fetch session summary from the session-store DB. Returns '' on failure."""
    import sqlite3

    from .constants import SESSION_STORE_DB

    try:
        conn = sqlite3.connect(f"file:{SESSION_STORE_DB}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT summary FROM sessions WHERE id = ? LIMIT 1", (session_id,)
        ).fetchone()
        conn.close()
        return row[0] if row and row[0] else ""
    except Exception:
        return ""


def _try_focus_wt_tab(hwnd, session_id, cached_hwnd=0):
    """Try to activate the correct Windows Terminal tab using UI Automation.

    Searches across ALL WT windows (they share one PID) to find the tab
    matching this session. Uses multiple match strategies (intent, summary).
    If *cached_hwnd* is set, tries that window first for speed.
    Returns (matched_hwnd, message) where matched_hwnd is the correct
    window to focus, or None if no match.
    """
    Application = _get_pywinauto_app()
    if Application is None:
        return None, ""

    try:
        import win32gui
        import win32process

        candidates = _get_session_match_candidates(session_id)
        if not candidates:
            return None, "No session summary or intent available for tab matching"

        # Collect ALL WT windows (they share one PID)
        _, wt_pid = win32process.GetWindowThreadProcessId(hwnd)
        wt_hwnds = []

        def enum_cb(h, _):
            if win32gui.IsWindowVisible(h):
                _, pid = win32process.GetWindowThreadProcessId(h)
                if pid == wt_pid and win32gui.GetWindowText(h):
                    wt_hwnds.append(h)
            return True

        win32gui.EnumWindows(enum_cb, None)

        # If we have a cached HWND, try it first
        if cached_hwnd and cached_hwnd in wt_hwnds:
            wt_hwnds.remove(cached_hwnd)
            wt_hwnds.insert(0, cached_hwnd)

        # Search each window's tabs for a match
        for wt_hwnd in wt_hwnds:
            try:
                app = Application(backend="uia").connect(handle=wt_hwnd)
                win = app.window(handle=wt_hwnd)
                tabs = win.descendants(control_type="TabItem")
                if not tabs:
                    continue
                for candidate in candidates:
                    for tab in tabs:
                        title = tab.window_text()
                        if candidate in title.lower():
                            if len(tabs) > 1:
                                iface = tab.iface_selection_item
                                if iface:
                                    iface.Select()
                            return wt_hwnd, f"Switched to tab: {title}"
            except Exception:
                continue

        tried = ", ".join(f"'{c}'" for c in candidates)
        return None, f"No tab matched (tried {tried})"
    except Exception as e:
        logger.debug("WT tab focus failed: %s", e)
        return None, ""


def _bring_hwnd_to_front(target_hwnd):
    """Bring a window handle to the foreground, even from a background process."""
    import ctypes

    import win32con
    import win32gui
    import win32process

    # windll is Windows-only; type: ignore keeps mypy happy on Linux
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    placement = win32gui.GetWindowPlacement(target_hwnd)
    if placement[1] == win32con.SW_SHOWMINIMIZED:
        win32gui.ShowWindow(target_hwnd, win32con.SW_RESTORE)

    fg_hwnd = win32gui.GetForegroundWindow()
    if fg_hwnd == target_hwnd:
        return  # already focused

    # Temporarily set foreground lock timeout to 0, allowing our
    # background process to steal focus.
    SPI_GETFOREGROUNDLOCKTIMEOUT = 0x2000
    SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001
    SPIF_SENDCHANGE = 0x0002
    old_timeout = ctypes.wintypes.DWORD()
    user32.SystemParametersInfoW(SPI_GETFOREGROUNDLOCKTIMEOUT, 0, ctypes.byref(old_timeout), 0)
    user32.SystemParametersInfoW(SPI_SETFOREGROUNDLOCKTIMEOUT, 0, None, SPIF_SENDCHANGE)

    fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
    my_thread = win32process.GetWindowThreadProcessId(target_hwnd)[0]
    if fg_thread != my_thread:
        user32.AttachThreadInput(fg_thread, my_thread, True)
    try:
        win32gui.BringWindowToTop(target_hwnd)
        win32gui.SetForegroundWindow(target_hwnd)
    finally:
        if fg_thread != my_thread:
            user32.AttachThreadInput(fg_thread, my_thread, False)

    user32.SystemParametersInfoW(
        SPI_SETFOREGROUNDLOCKTIMEOUT,
        0,
        ctypes.cast(old_timeout.value, ctypes.c_void_p),
        SPIF_SENDCHANGE,
    )


def _focus_session_window_windows(session_id, sessions: dict[str, ProcessInfo]):
    """Focus terminal window on Windows using pywin32."""
    try:
        import win32gui
        import win32process
    except ImportError:
        return False, "pywin32 not installed. Run: session_dashboard.py install"

    info = sessions[session_id]
    copilot_pid = info.pid
    terminal_pid = info.terminal_pid
    terminal_name = info.terminal_name

    if not terminal_pid:
        diag = _build_diagnostics(copilot_pid, terminal_pid, terminal_name)
        return False, f"Could not find terminal window.\n{diag}"

    is_wt = terminal_name.lower() in ("windowsterminal.exe", "wt.exe")

    # For WT, prefer the cached HWND from _populate_window_titles
    if is_wt and info.terminal_hwnd:
        try:
            matched_hwnd, tab_msg = _try_focus_wt_tab(
                info.terminal_hwnd, session_id, cached_hwnd=info.terminal_hwnd
            )
            if matched_hwnd:
                _bring_hwnd_to_front(matched_hwnd)
                title = win32gui.GetWindowText(matched_hwnd)
                msg = f"Focused: {title}"
                if tab_msg:
                    msg += f"\n{tab_msg}"
                return True, msg
        except Exception:
            pass  # fall through to full search below

    # Find any visible window for this terminal PID (as a fallback)
    fallback_hwnd = None

    def enum_cb(hwnd, _):
        nonlocal fallback_hwnd
        if win32gui.IsWindowVisible(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid == terminal_pid:
                title = win32gui.GetWindowText(hwnd)
                if title:
                    fallback_hwnd = hwnd
        return True

    win32gui.EnumWindows(enum_cb, None)
    if not fallback_hwnd:
        diag = _build_diagnostics(copilot_pid, terminal_pid, terminal_name)
        return False, f"No visible window found for terminal PID {terminal_pid}.\n{diag}"

    try:
        target_hwnd = fallback_hwnd
        tab_msg = ""

        # For WT, search all windows for the tab matching this session.
        if is_wt:
            matched_hwnd, tab_msg = _try_focus_wt_tab(fallback_hwnd, session_id)
            if matched_hwnd:
                target_hwnd = matched_hwnd
            else:
                # No tab match — don't focus a random window
                return False, (
                    f"Could not identify the correct terminal tab for this session.\n{tab_msg}"
                )

        _bring_hwnd_to_front(target_hwnd)
        title = win32gui.GetWindowText(target_hwnd)
        msg = f"Focused: {title}"
        if tab_msg:
            msg += f"\n{tab_msg}"
        return True, msg
    except Exception as e:
        diag = _build_diagnostics(copilot_pid, terminal_pid, terminal_name)
        return False, f"Could not focus window: {e}\n{diag}"


def _focus_session_window_macos(session_id, sessions: dict[str, ProcessInfo]):
    """Focus terminal window on macOS using osascript."""
    info = sessions[session_id]
    terminal_name = info.terminal_name

    # Map process name to application name for AppleScript
    app_name = None
    tn = terminal_name.lower()
    for substring, name in MACOS_APP_NAMES.items():
        if substring in tn:
            app_name = name
            break

    if not app_name:
        # Fallback: use the first known terminal app
        for candidate in MACOS_FALLBACK_TERMINALS:
            app_name = candidate
            break

    if not app_name:
        return False, "Could not determine terminal application."

    # Validate app_name is in our known-safe allowlist to prevent injection
    allowed = set(MACOS_APP_NAMES.values()) | set(MACOS_FALLBACK_TERMINALS)
    if app_name not in allowed:
        return False, f"Unknown terminal application: {app_name}"

    try:
        script = f'tell application "{app_name}" to activate'
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=OSASCRIPT_TIMEOUT,
            check=False,
        )
        if result.returncode == 0:
            return True, f"Focused: {app_name}"
        return False, f"osascript failed: {result.stderr.strip()}"
    except Exception as e:
        return False, f"Could not focus window: {e}"


def focus_session_window(session_id):
    """
    Bring the terminal window running a session to the foreground.
    Returns (success: bool, message: str).

    Uses cached process data when available to avoid a ~1s WMI query.
    The cache is kept warm by the dashboard's regular polling cycle.
    """
    # Prefer cached data (even if stale) to avoid blocking on a fresh WMI query.
    sessions = _running_cache.data if _running_cache.data else get_running_sessions()
    if session_id not in sessions:
        # Cache miss — try a fresh query as fallback
        sessions = get_running_sessions()
    if session_id not in sessions:
        return False, "Session not found among running processes."

    if sys.platform == "win32":
        return _focus_session_window_windows(session_id, sessions)
    if sys.platform == "darwin":
        return _focus_session_window_macos(session_id, sessions)
    return False, "Window focus not supported on this platform."
