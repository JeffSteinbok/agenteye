"""Microsoft Scout session reader for Agent Eye.

Scout embeds Copilot CLI and stores its session data under
``~/.scout/copilot/`` using the same SQLite/events schema as Copilot CLI.
This module reads that alternate root and exposes Scout sessions with a
dedicated ID prefix so they can appear alongside normal Copilot sessions.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from collections import Counter
from datetime import UTC, datetime

from .constants import (
    EVENT_TAIL_BUFFER,
    MTIME_ACTIVE_THRESHOLD,
    OUTPUT_TAIL_BUFFER,
    SCOUT_SESSION_STATE_DIR,
    SCOUT_SESSION_STORE_DB,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
)
from .grouping import get_group_name
from .models import BackgroundTask, EventData, ProcessInfo, SessionState

logger = logging.getLogger(__name__)

SESSION_ID_PREFIX = "scout:"

WAITING_TOOLS = frozenset({"ask_user", "ask_permission"})
NON_CONVERSATIONAL_EVENTS = frozenset(
    {
        "hook.start",
        "hook.end",
        "session.start",
        "session.resume",
        "session.shutdown",
        "session.model_change",
        "session.mode_changed",
        "session.task_complete",
        "session.context_changed",
        "session.warning",
        "subagent.selected",
        "system.message",
    }
)

_SESSIONS_QUERY = """
    SELECT
        s.id, s.cwd, s.repository, s.branch, s.summary,
        s.created_at, s.updated_at,
        (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) as turn_count,
        (SELECT COUNT(*) FROM session_files sf WHERE sf.session_id = s.id) as file_count,
        (SELECT COUNT(*) FROM checkpoints cp WHERE cp.session_id = s.id) as checkpoint_count,
        (SELECT user_message FROM turns t WHERE t.session_id = s.id AND t.turn_index = 0) as first_msg,
        (SELECT assistant_response FROM turns t WHERE t.session_id = s.id AND t.turn_index = 0) as first_asst,
        (SELECT title FROM checkpoints c WHERE c.session_id = s.id ORDER BY checkpoint_number DESC LIMIT 1) as last_cp_title,
        (SELECT overview FROM checkpoints c WHERE c.session_id = s.id ORDER BY checkpoint_number DESC LIMIT 1) as last_cp_overview
    FROM sessions s
    ORDER BY s.updated_at DESC
"""

_event_data_cache: dict[str, EventData] = {}


def _raw_session_id(session_id: str) -> str:
    return (
        session_id[len(SESSION_ID_PREFIX) :]
        if session_id.startswith(SESSION_ID_PREFIX)
        else session_id
    )


def _clean_scout_summary(raw: str) -> str:
    """Strip Scout-injected system context from a raw session summary/turn message.

    Scout injects ``[Microsoft Scout context: ...]`` blocks and sometimes stores
    full conversation transcripts or internal prompts as the session summary.
    This strips all of that to leave only the actual user-visible request.
    """
    if not raw:
        return ""
    s = raw.strip()
    # "Conversation:\n\nuser: <msg>\n\nA: ..." — extract just the user part
    if s.lower().startswith("conversation:"):
        import re

        m = re.search(r"user:\s*(.+?)(?:\n\nA:|$)", s, re.IGNORECASE | re.DOTALL)
        if m:
            s = m.group(1).strip()
    # Strip "USER ASKED: " prefix
    if s.upper().startswith("USER ASKED:"):
        s = s[len("USER ASKED:") :].strip()
    # Strip "[Microsoft Scout context: ...]" and everything after it
    scout_ctx = s.find("[Microsoft Scout context:")
    if scout_ctx != -1:
        s = s[:scout_ctx].strip()
    # Truncate and return
    return s[:120] if s else ""


def _events_file(session_id: str) -> str:
    return os.path.join(SCOUT_SESSION_STATE_DIR, _raw_session_id(session_id), "events.jsonl")


def _time_ago(iso_str: str | None) -> str:
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        seconds = int((datetime.now(UTC) - dt).total_seconds())
        if seconds < SECONDS_PER_MINUTE:
            return f"{seconds}s ago"
        if seconds < SECONDS_PER_HOUR:
            return f"{seconds // SECONDS_PER_MINUTE}m ago"
        if seconds < SECONDS_PER_DAY:
            return f"{seconds // SECONDS_PER_HOUR}h ago"
        return f"{seconds // SECONDS_PER_DAY}d ago"
    except Exception:
        return iso_str or "unknown"


def _get_db() -> sqlite3.Connection:
    if not os.path.exists(SCOUT_SESSION_STORE_DB):
        raise FileNotFoundError(SCOUT_SESSION_STORE_DB)
    conn = sqlite3.connect(f"file:{SCOUT_SESSION_STORE_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _read_recent_events(session_id: str, count: int = 30) -> list[dict]:
    path = _events_file(session_id)
    if not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_from = max(0, size - EVENT_TAIL_BUFFER)
            f.seek(read_from)
            chunk = f.read().decode("utf-8", errors="replace")
        raw_lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if read_from > 0 and raw_lines:
            raw_lines = raw_lines[1:]
        events = []
        for line in raw_lines[-count:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping malformed Scout event line in %s", session_id)
        return events
    except Exception as e:
        logger.debug("Error reading Scout events for %s: %s", session_id, e)
        return []


def _get_session_state(session_id: str) -> SessionState:
    events = _read_recent_events(session_id)
    if not events:
        return SessionState(state="unknown", waiting_context="", bg_tasks=0, bg_task_list=[])

    pending_tools: dict[str, dict] = {}
    for ev in events:
        etype = ev.get("type", "")
        data = ev.get("data", {})
        if etype == "tool.execution_start":
            tool_call_id = data.get("toolCallId", "")
            if tool_call_id:
                pending_tools[tool_call_id] = data
        elif etype == "tool.execution_complete":
            pending_tools.pop(data.get("toolCallId", ""), None)

    bg_task_list = _get_running_background_tasks(session_id)
    bg = len(bg_task_list)
    for data in pending_tools.values():
        tool = data.get("toolName", "")
        if tool in WAITING_TOOLS:
            args = data.get("arguments", {})
            question = args.get("question", "") if isinstance(args, dict) else ""
            return SessionState(
                state="waiting",
                waiting_context=question,
                bg_tasks=bg,
                bg_task_list=bg_task_list,
            )
        if tool != "report_intent":
            return SessionState(
                state="working", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
            )

    last = next(
        (ev for ev in reversed(events) if ev.get("type", "") not in NON_CONVERSATIONAL_EVENTS),
        None,
    )
    if last is None:
        return SessionState(
            state="unknown", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )

    etype = last.get("type", "")
    data = last.get("data", {})
    if etype == "assistant.turn_end":
        return SessionState(
            state="idle",
            waiting_context="Session idle - waiting for user message",
            bg_tasks=bg,
            bg_task_list=bg_task_list,
        )
    if etype == "tool.execution_start":
        tool = data.get("toolName", "")
        if tool in WAITING_TOOLS:
            args = data.get("arguments", {})
            question = args.get("question", "") if isinstance(args, dict) else ""
            return SessionState(
                state="waiting",
                waiting_context=question,
                bg_tasks=bg,
                bg_task_list=bg_task_list,
            )
        return SessionState(
            state="working", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    if etype in {
        "tool.execution_complete",
        "subagent.completed",
        "assistant.turn_start",
        "assistant.message",
        "user.message",
    }:
        return SessionState(
            state="thinking", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list
        )
    return SessionState(state="unknown", waiting_context="", bg_tasks=bg, bg_task_list=bg_task_list)


def _get_running_background_tasks(session_id: str) -> list[BackgroundTask]:
    path = _events_file(session_id)
    if not os.path.exists(path):
        return []
    started: dict[str, BackgroundTask] = {}
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"subagent.started"' in line:
                    try:
                        evt = json.loads(line)
                        data = evt.get("data", {})
                        tool_call_id = data.get("toolCallId", "")
                        if tool_call_id:
                            started[tool_call_id] = BackgroundTask(
                                agent_name=data.get("agentDisplayName")
                                or data.get("agentName", ""),
                                description=data.get("agentDescription", ""),
                            )
                    except Exception:
                        pass
                elif '"subagent.completed"' in line:
                    try:
                        evt = json.loads(line)
                        started.pop(evt.get("data", {}).get("toolCallId", ""), None)
                    except Exception:
                        pass
    except OSError as e:
        logger.debug("Error reading Scout background tasks for %s: %s", session_id, e)
    return list(started.values())


def _read_event_data(session_id: str) -> EventData:
    result = EventData()
    path = _events_file(session_id)
    if not os.path.exists(path):
        return result

    try:
        mcp_found = False
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"session.start"' in line or '"session.resume"' in line:
                    try:
                        evt = json.loads(line)
                        ctx = evt.get("data", {}).get("context", {})
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
                        result.intent = args.get("intent", "") or result.intent
                    except (json.JSONDecodeError, TypeError):
                        pass
                    continue
                if '"tool.execution_complete"' in line:
                    result.tool_calls += 1
                if '"subagent.completed"' in line:
                    result.subagent_runs += 1
    except Exception as e:
        logger.debug("Error reading Scout event data for %s: %s", session_id, e)
    return result


def get_scout_session_event_data(session_id: str, is_running: bool = False) -> EventData:
    raw_id = _raw_session_id(session_id)
    if not is_running and raw_id in _event_data_cache:
        return _event_data_cache[raw_id]
    data = _read_event_data(raw_id)
    if not is_running:
        _event_data_cache[raw_id] = data
    return data


def _is_completed(session_id: str) -> bool:
    path = _events_file(session_id)
    if not os.path.exists(path):
        return False
    last_lifecycle = ""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if (
                    "session.start" in line
                    or "session.resume" in line
                    or "session.shutdown" in line
                ):
                    try:
                        last_lifecycle = json.loads(line).get("type", "") or last_lifecycle
                    except json.JSONDecodeError:
                        pass
    except OSError:
        return False
    return last_lifecycle == "session.shutdown"


def get_running_scout_sessions() -> dict[str, ProcessInfo]:
    """Return Scout sessions with recently updated event logs.

    Scout uses one long-lived headless Copilot process for the app, so there
    is not a safe one-process-per-session PID to kill or focus. Recent mtime is
    the best session-level liveness signal, matching the existing VS Code
    integrated-session behavior.
    """
    if not os.path.isdir(SCOUT_SESSION_STATE_DIR):
        return {}
    result: dict[str, ProcessInfo] = {}
    now = time.time()
    try:
        for sid in os.listdir(SCOUT_SESSION_STATE_DIR):
            path = _events_file(sid)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if now - mtime > MTIME_ACTIVE_THRESHOLD or _is_completed(sid):
                continue
            state = _get_session_state(sid)
            result[SESSION_ID_PREFIX + sid] = ProcessInfo(
                pid=0,
                parent_pid=0,
                cmdline="Microsoft Scout embedded Copilot",
                state=state["state"],
                waiting_context=state["waiting_context"],
                bg_tasks=state["bg_tasks"],
                bg_task_list=state["bg_task_list"],
            )
    except OSError as e:
        logger.debug("Error scanning Scout session-state: %s", e)
    return result


def _build_restart_cmd(raw_id: str, cwd: str) -> str:
    parts: list[str] = []
    if cwd:
        parts.append(f'cd "{cwd}" &&')
    parts.append(f"scout --resume {raw_id}")
    return " ".join(parts)


def _recent_activity(session: dict) -> str:
    last_cp_title = session.get("last_cp_title") or ""
    summary = session.get("summary") or ""
    return last_cp_title if last_cp_title and last_cp_title.lower() != summary.lower() else ""


def _enrich_session(session: dict, proc: ProcessInfo | None, evt: EventData) -> dict:
    raw_id = str(session["id"])
    session["id"] = SESSION_ID_PREFIX + raw_id
    session["source"] = "scout"
    session["summary"] = _clean_scout_summary(session.get("summary") or "")
    session["time_ago"] = _time_ago(session.get("updated_at"))
    session["created_ago"] = _time_ago(session.get("created_at"))
    session["is_running"] = proc is not None
    session["state"] = proc.state if proc else None
    session["waiting_context"] = proc.waiting_context if proc else ""
    session["bg_tasks"] = proc.bg_tasks if proc else 0
    if not session.get("cwd") and evt.cwd:
        session["cwd"] = evt.cwd
    if evt.branch and (not session.get("branch") or proc is not None):
        session["branch"] = evt.branch
    if not session.get("repository") and evt.repository:
        session["repository"] = evt.repository
    session["group"] = get_group_name(session)
    session["recent_activity"] = _recent_activity(session)
    session["restart_cmd"] = _build_restart_cmd(raw_id, session.get("cwd") or "")
    session["mcp_servers"] = proc.mcp_servers if proc else evt.mcp_servers
    session["tool_calls"] = evt.tool_calls
    session["subagent_runs"] = evt.subagent_runs
    session["intent"] = evt.intent
    session.pop("last_cp_overview", None)
    session.pop("last_cp_title", None)
    # Use Scout's LLM-generated title (assistant_response of the title-gen turn) when present
    first_msg = session.pop("first_msg", None) or ""
    first_asst = session.pop("first_asst", None) or ""
    if first_asst and first_msg.lstrip().lower().startswith("conversation:"):
        session["summary"] = first_asst.strip()[:120]
    return session


def get_scout_sessions(running: dict[str, ProcessInfo] | None = None) -> list[dict]:
    if running is None:
        running = get_running_scout_sessions()
    if not os.path.exists(SCOUT_SESSION_STORE_DB):
        return _sessions_from_events(running)

    sessions: list[dict] = []
    try:
        db = _get_db()
        try:
            rows = db.execute(_SESSIONS_QUERY).fetchall()
        finally:
            db.close()
        for row in rows:
            session = dict(row)
            prefixed_id = SESSION_ID_PREFIX + str(session["id"])
            proc = running.get(prefixed_id)
            evt = get_scout_session_event_data(prefixed_id, is_running=proc is not None)
            sessions.append(_enrich_session(session, proc, evt))
    except Exception as e:
        logger.debug("Error reading Scout session-store: %s", e)
        return _sessions_from_events(running)
    return sessions


def _sessions_from_events(running: dict[str, ProcessInfo]) -> list[dict]:
    if not os.path.isdir(SCOUT_SESSION_STATE_DIR):
        return []
    sessions: list[dict] = []
    try:
        session_ids = os.listdir(SCOUT_SESSION_STATE_DIR)
    except OSError:
        return sessions
    for sid in session_ids:
        path = _events_file(sid)
        if not os.path.exists(path):
            continue
        created_at = ""
        updated_at = ""
        summary = ""
        turn_count = 0
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"timestamp"' not in line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = evt.get("timestamp", "")
                    if ts:
                        created_at = created_at or ts
                        updated_at = ts
                    if evt.get("type") == "user.message" and not summary:
                        content = evt.get("data", {}).get("content", "")
                        if content:
                            summary = _clean_scout_summary(str(content)) or str(content)[:120]
                    elif evt.get("type") == "assistant.turn_end":
                        turn_count += 1
        except OSError:
            continue
        if not created_at:
            continue
        prefixed_id = SESSION_ID_PREFIX + sid
        proc = running.get(prefixed_id)
        evt = get_scout_session_event_data(prefixed_id, is_running=proc is not None)
        session = {
            "id": sid,
            "cwd": evt.cwd,
            "repository": evt.repository,
            "branch": evt.branch,
            "summary": summary or "(No summary)",
            "created_at": created_at,
            "updated_at": updated_at or created_at,
            "turn_count": turn_count,
            "file_count": 0,
            "checkpoint_count": 0,
            "first_msg": None,
            "last_cp_title": None,
            "last_cp_overview": None,
        }
        sessions.append(_enrich_session(session, proc, evt))
    return sessions


def get_scout_session_cwd(session_id: str) -> str | None:
    raw_id = _raw_session_id(session_id)
    try:
        db = _get_db()
    except FileNotFoundError:
        db = None
    if db is not None:
        try:
            row = db.execute("SELECT cwd FROM sessions WHERE id = ?", (raw_id,)).fetchone()
            if row and row["cwd"]:
                return str(row["cwd"])
        finally:
            db.close()
    evt = get_scout_session_event_data(raw_id)
    return evt.cwd or None


def get_recent_scout_output(session_id: str, max_lines: int = 10) -> list[str]:
    path = _events_file(session_id)
    if not os.path.exists(path):
        return []
    try:
        output_lines: list[str] = []
        with open(path, "rb") as f:
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
            except json.JSONDecodeError:
                continue
            if event.get("type") != "tool.execution_complete":
                continue
            content = event.get("data", {}).get("result", {}).get("content", "")
            if content and len(content) >= 5 and content.strip() != "Intent logged":
                output_lines = content.strip().split("\n")
        return output_lines[-max_lines:] if output_lines else []
    except Exception as e:
        logger.debug("Error reading Scout output for %s: %s", session_id, e)
        return []


def get_scout_session_detail(session_id: str) -> dict:
    raw_id = _raw_session_id(session_id)
    tool_counter: Counter = Counter()
    path = _events_file(raw_id)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"tool.execution_start"' not in line:
                        continue
                    try:
                        evt = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "tool.execution_start":
                        tool_name = evt.get("data", {}).get("toolName", "")
                        if tool_name:
                            tool_counter[tool_name] += 1
        except OSError:
            pass

    try:
        db = _get_db()
    except FileNotFoundError:
        return {
            "checkpoints": [],
            "refs": [],
            "turns": [],
            "recent_output": get_recent_scout_output(raw_id),
            "tool_counts": [{"name": k, "count": v} for k, v in tool_counter.most_common(10)],
            "files": [],
        }

    try:
        checkpoints = db.execute(
            "SELECT checkpoint_number, title, overview, next_steps "
            "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number",
            (raw_id,),
        ).fetchall()
        refs = db.execute(
            "SELECT ref_type, ref_value FROM session_refs WHERE session_id = ?",
            (raw_id,),
        ).fetchall()
        turns = db.execute(
            "SELECT turn_index, user_message, assistant_response "
            "FROM turns WHERE session_id = ? ORDER BY turn_index DESC LIMIT 10",
            (raw_id,),
        ).fetchall()
        files = db.execute(
            "SELECT DISTINCT file_path FROM session_files WHERE session_id = ? ORDER BY file_path",
            (raw_id,),
        ).fetchall()
    finally:
        db.close()

    return {
        "checkpoints": [dict(r) for r in checkpoints],
        "refs": [dict(r) for r in refs],
        "turns": [dict(r) for r in reversed(turns)],
        "recent_output": get_recent_scout_output(raw_id),
        "tool_counts": [{"name": k, "count": v} for k, v in tool_counter.most_common(10)],
        "files": [r["file_path"] for r in files],
    }
