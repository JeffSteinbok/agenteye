"""
Copilot Dashboard — FastAPI web application.

Serves a real-time dashboard of all Copilot CLI sessions with:
  - Active vs Previous session split
  - Project-area grouping
  - Restart commands with copy buttons
  - Click-to-focus terminal windows
  - Light/dark mode and palette selector
  - Auto-generated OpenAPI docs at /docs
"""

import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .__version__ import __version__
from .claude_code import (
    SESSION_ID_PREFIX as CC_PREFIX,
)
from .claude_code import (
    get_claude_session_detail,
    get_claude_sessions,
    get_running_claude_sessions,
)
from .constants import (
    DASHBOARD_CONFIG_PATH,
    PYPI_FETCH_TIMEOUT,
    PYPI_PACKAGE_URL,
    RECENT_ACTIVITY_MAX_LEN,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SECONDS_PER_MINUTE,
    SESSION_STATE_DIR,
    SESSION_STORE_DB,
    SYNC_EXPORT_INTERVAL,
    VERSION_CACHE_TTL,
)
from .grouping import get_group_name
from .models import EventData, ProcessInfo, VersionCache
from .process_tracker import (
    focus_session_window,
    get_recent_output,
    get_running_sessions,
    get_session_event_data,
)
from .schemas import (
    ActionResponse,
    AutostartStatusResponse,
    FileEntryResponse,
    ProcessResponse,
    ServerInfoResponse,
    SessionDetailResponse,
    SessionResponse,
    SettingsResponse,
    VersionResponse,
)
from .sync import export_sessions, read_remote_sessions, resolve_sync_folder

logger = logging.getLogger(__name__)

# Strict pattern for session IDs — UUID-like strings, optionally prefixed with "cc:"
_SESSION_ID_RE = re.compile(r"^(cc:)?[a-zA-Z0-9_-]+$")

# ── App setup ────────────────────────────────────────────────────────────────

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(PKG_DIR, "static")
DIST_DIR = os.path.join(STATIC_DIR, "dist")
TEMPLATES_DIR = os.path.join(PKG_DIR, "templates")

DB_PATH = SESSION_STORE_DB
_version_cache = VersionCache()
_version_lock = threading.Lock()
_sync_folder = resolve_sync_folder()

# ── Background sync ─────────────────────────────────────────────────────────

_sync_stop = threading.Event()


def _sync_loop() -> None:
    """Periodically export active sessions to the sync folder."""
    while not _sync_stop.wait(timeout=SYNC_EXPORT_INTERVAL):
        if not _sync_folder:
            continue
        try:
            sessions = _build_session_list()
            active = [s for s in sessions if s.get("is_running")]
            export_sessions(active, _sync_folder)
        except Exception:
            logger.debug("Background sync export failed", exc_info=True)


def _build_session_list() -> list[dict]:
    """Build the session list (shared by /api/sessions and the sync loop)."""
    result: list[dict] = []

    try:
        db = get_db()
        try:
            rows = db.execute(_SESSIONS_QUERY).fetchall()
        finally:
            db.close()

        running = get_running_sessions()
        for r in rows:
            s = dict(r)
            s["source"] = "copilot"
            proc = running.get(s["id"])
            evt = get_session_event_data(s["id"], is_running=proc is not None)
            result.append(_enrich_session(s, proc, evt))
    except FileNotFoundError:
        logger.debug("Copilot session store not found, falling back to events.jsonl")
        result.extend(_sessions_from_events())

    try:
        claude_running = get_running_claude_sessions()
        claude_sessions = get_claude_sessions(running=claude_running)
        result.extend(claude_sessions)
    except Exception:
        logger.exception("Error loading Claude Code sessions")

    result.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return result


@asynccontextmanager
async def _lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Start background sync thread on startup, stop it on shutdown."""
    sync_thread: threading.Thread | None = None
    if _sync_folder:
        sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="sync-export")
        sync_thread.start()
        logger.info("Background sync started (interval=%ds)", SYNC_EXPORT_INTERVAL)

    yield

    _sync_stop.set()
    if sync_thread is not None:
        sync_thread.join(timeout=5)
        logger.info("Background sync stopped")


app = FastAPI(
    title="Copilot Dashboard",
    version=__version__,
    description="Monitor all your GitHub Copilot CLI sessions in real-time.",
    lifespan=_lifespan,
)

# ── Security ─────────────────────────────────────────────────────────────────

# Per-instance token generated at startup; required on all /api/* requests.
API_TOKEN: str = secrets.token_urlsafe(32)

# CORS: only allow same-origin requests (no cross-origin API access)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],  # no cross-origin allowed
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization"],
)

# Paths that are exempt from token validation
_PUBLIC_PATH_PREFIXES = (
    "/static",
    "/assets",
    "/favicon",
    "/manifest",
    "/sw.js",
    "/docs",
    "/openapi.json",
)


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Require a valid token on /api/* requests."""
    path = request.url.path
    if path.startswith("/api/"):
        token = request.query_params.get("token")
        if not token:
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
        if token != API_TOKEN:
            return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return await call_next(request)


# Mount /static for legacy assets (favicon, icons, etc.)
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _validate_session_id(session_id: str) -> str | None:
    """Return an error message if session_id is invalid, else None."""
    if not _SESSION_ID_RE.match(session_id):
        return "Invalid session ID format"
    return None


def get_db() -> sqlite3.Connection:
    """Open the session-store database in read-only mode."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(
            f"Session store not found at {DB_PATH}. "
            "Enable the SESSION_STORE experimental feature by adding "
            '"experimental": true to ~/.copilot/config.json, '
            "then start a new Copilot session."
        )
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def time_ago(iso_str: str | None) -> str:
    """Convert an ISO timestamp to a human-readable relative time string."""
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        seconds = int((now - dt).total_seconds())
        if seconds < SECONDS_PER_MINUTE:
            return f"{seconds}s ago"
        if seconds < SECONDS_PER_HOUR:
            return f"{seconds // SECONDS_PER_MINUTE}m ago"
        if seconds < SECONDS_PER_DAY:
            return f"{seconds // SECONDS_PER_HOUR}h ago"
        return f"{seconds // SECONDS_PER_DAY}d ago"
    except Exception:
        return iso_str


def get_recent_activity(session: dict) -> str:
    """Short description of recent activity from the latest checkpoint."""
    last_cp_title = session.get("last_cp_title") or ""
    last_cp_overview = session.get("last_cp_overview") or ""
    summary = session.get("summary") or ""

    if last_cp_title and last_cp_title.lower() != summary.lower():
        return last_cp_title
    if last_cp_overview:
        first_sentence = last_cp_overview.split(". ")[0]
        if len(first_sentence) > RECENT_ACTIVITY_MAX_LEN:
            return first_sentence[: RECENT_ACTIVITY_MAX_LEN - 3] + "..."
        return first_sentence
    return ""


def _extract_extra_args(cmdline: str) -> str:
    """Extract extra CLI arguments from a copilot process command line."""
    if not cmdline:
        return ""
    import shlex

    try:
        parts = shlex.split(cmdline, posix=(os.name != "nt"))
    except ValueError:
        parts = cmdline.split()

    start = 0
    for i, p in enumerate(parts):
        if "copilot" in p.lower():
            start = i + 1
            break

    extra: list[str] = []
    skip_next = False
    for p in parts[start:]:
        if skip_next:
            skip_next = False
            continue
        if p in ("--resume", "--log-dir"):
            skip_next = True
            continue
        extra.append(p)
    return " ".join(extra)


def build_restart_command(
    session: dict,
    yolo: bool = False,
    cmdline: str = "",
    agency: bool = False,
) -> str:
    """Build a restart command for a session."""
    sid = session["id"]
    cwd = session.get("cwd") or ""
    parts: list[str] = []
    if cwd:
        parts.append(f'cd "{cwd}" &&')
    prefix = "agency copilot" if agency else "copilot"
    cmd = f"{prefix} --resume {sid}"
    extra = _extract_extra_args(cmdline)
    if extra:
        cmd += " " + extra
    elif yolo:
        cmd += " --yolo"
    parts.append(cmd)
    return " ".join(parts)


# ── Session query helpers ────────────────────────────────────────────────────

_SESSIONS_QUERY = """
    SELECT
        s.id, s.cwd, s.repository, s.branch, s.summary,
        s.created_at, s.updated_at,
        (SELECT COUNT(*) FROM turns t WHERE t.session_id = s.id) as turn_count,
        (SELECT COUNT(*) FROM session_files sf WHERE sf.session_id = s.id) as file_count,
        (SELECT COUNT(*) FROM checkpoints cp WHERE cp.session_id = s.id) as checkpoint_count,
        (SELECT user_message FROM turns t WHERE t.session_id = s.id AND t.turn_index = 0) as first_msg,
        (SELECT title FROM checkpoints c WHERE c.session_id = s.id ORDER BY checkpoint_number DESC LIMIT 1) as last_cp_title,
        (SELECT overview FROM checkpoints c WHERE c.session_id = s.id ORDER BY checkpoint_number DESC LIMIT 1) as last_cp_overview
    FROM sessions s
    ORDER BY s.updated_at DESC
"""


def _enrich_session(s: dict, proc: ProcessInfo | None, evt: EventData) -> dict:
    """Enrich a raw session row with computed fields."""
    s["time_ago"] = time_ago(s["updated_at"])
    s["created_ago"] = time_ago(s["created_at"])
    is_running = proc is not None
    s["is_running"] = is_running

    if proc:
        s["state"] = proc.state
        s["waiting_context"] = proc.waiting_context
        s["bg_tasks"] = proc.bg_tasks
    else:
        s["state"] = None
        s["waiting_context"] = ""
        s["bg_tasks"] = 0

    # Backfill cwd/branch/repo from events when SQL has NULLs
    if not s.get("cwd") and evt.cwd:
        s["cwd"] = evt.cwd
    if not s.get("branch") and evt.branch:
        s["branch"] = evt.branch
    if not s.get("repository") and evt.repository:
        s["repository"] = evt.repository

    s["group"] = get_group_name(s)
    s["recent_activity"] = get_recent_activity(s)
    s["restart_cmd"] = build_restart_command(
        s,
        yolo=proc.yolo if proc else False,
        cmdline=proc.cmdline if proc else "",
        agency=proc.agency if proc else False,
    )
    s["mcp_servers"] = proc.mcp_servers if proc else evt.mcp_servers
    s["tool_calls"] = evt.tool_calls
    s["subagent_runs"] = evt.subagent_runs
    s["intent"] = evt.intent

    # Don't send large text fields to the client
    s.pop("first_msg", None)
    s.pop("last_cp_overview", None)
    s.pop("last_cp_title", None)
    return s


def _sessions_from_events() -> list[dict]:
    """Build Copilot session list from events.jsonl when session-store.db is absent.

    Scans ``~/.copilot/session-state/*/events.jsonl`` to extract session
    metadata (cwd, branch, summary, timestamps, turn counts) so the
    dashboard still works without the experimental SESSION_STORE feature.
    """
    if not os.path.isdir(SESSION_STATE_DIR):
        return []

    running = get_running_sessions()
    sessions: list[dict] = []

    for entry in os.listdir(SESSION_STATE_DIR):
        session_dir = os.path.join(SESSION_STATE_DIR, entry)
        events_file = os.path.join(session_dir, "events.jsonl")
        if not os.path.isdir(session_dir) or not os.path.isfile(events_file):
            continue

        sid = entry
        created_at = ""
        updated_at = ""
        cwd = ""
        branch = ""
        repository = ""
        summary = ""
        turn_count = 0

        try:
            with open(events_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Extract timestamp from every line (lightweight)
                    if '"timestamp"' in line:
                        try:
                            evt = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = evt.get("timestamp", "")
                        if ts:
                            if not created_at:
                                created_at = ts
                            updated_at = ts

                        etype = evt.get("type", "")

                        if etype in ("session.start", "session.resume"):
                            ctx = evt.get("data", {}).get("context", {})
                            # Always overwrite so the latest resume context wins
                            if ctx.get("cwd"):
                                cwd = ctx["cwd"]
                            if ctx.get("branch"):
                                branch = ctx["branch"]
                            if ctx.get("repository"):
                                repository = ctx["repository"]

                        elif etype == "user.message" and not summary:
                            content = evt.get("data", {}).get("content", "")
                            if content:
                                summary = content[:200]

                        elif etype == "assistant.turn_end":
                            turn_count += 1
        except OSError as e:
            logger.debug("Error reading events for %s: %s", sid, e)
            continue

        if not created_at:
            continue

        proc = running.get(sid)
        evt = get_session_event_data(sid, is_running=proc is not None)

        s: dict = {
            "id": sid,
            "cwd": cwd,
            "repository": repository,
            "branch": branch,
            "summary": summary or "(No summary)",
            "created_at": created_at,
            "updated_at": updated_at or created_at,
            "turn_count": turn_count,
            "file_count": 0,
            "checkpoint_count": 0,
            "first_msg": None,
            "last_cp_title": None,
            "last_cp_overview": None,
            "source": "copilot",
        }
        result = _enrich_session(s, proc, evt)
        sessions.append(result)

    return sessions


# ── API Routes ───────────────────────────────────────────────────────────────


@app.get("/api/sessions", response_model=list[SessionResponse])
def api_sessions():
    """List all sessions with enriched metadata."""
    return _build_session_list()


@app.get("/api/session/{session_id:path}", response_model=SessionDetailResponse)
def api_session_detail(session_id: str):
    """Get detailed info for a single session."""
    err = _validate_session_id(session_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    # Route Claude Code sessions to their own reader
    if session_id.startswith(CC_PREFIX):
        raw_id = session_id[len(CC_PREFIX) :]
        return get_claude_session_detail(raw_id)

    try:
        db = get_db()
    except FileNotFoundError:
        # No DB — return what we can from events.jsonl alone
        events_file = os.path.join(SESSION_STATE_DIR, session_id, "events.jsonl")
        tool_counter: Counter = Counter()
        if os.path.exists(events_file):
            try:
                with open(events_file, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if '"tool.execution_start"' in line:
                            try:
                                evt = json.loads(line)
                                if evt.get("type") == "tool.execution_start":
                                    tool_name = evt.get("data", {}).get("toolName", "")
                                    if tool_name:
                                        tool_counter[tool_name] += 1
                            except Exception:
                                pass
            except Exception:
                pass
        return {
            "checkpoints": [],
            "refs": [],
            "turns": [],
            "recent_output": get_recent_output(session_id),
            "tool_counts": [{"name": k, "count": v} for k, v in tool_counter.most_common(10)],
            "files": [],
        }
    try:
        checkpoints = db.execute(
            "SELECT checkpoint_number, title, overview, next_steps "
            "FROM checkpoints WHERE session_id = ? ORDER BY checkpoint_number",
            (session_id,),
        ).fetchall()
        refs = db.execute(
            "SELECT ref_type, ref_value FROM session_refs WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        turns = db.execute(
            "SELECT turn_index, user_message, assistant_response "
            "FROM turns WHERE session_id = ? ORDER BY turn_index DESC LIMIT 10",
            (session_id,),
        ).fetchall()
        files = db.execute(
            "SELECT DISTINCT file_path FROM session_files WHERE session_id = ? ORDER BY file_path",
            (session_id,),
        ).fetchall()
    finally:
        db.close()

    # Read tool counts from events.jsonl
    events_file = os.path.join(SESSION_STATE_DIR, session_id, "events.jsonl")
    tool_counter = Counter()
    if os.path.exists(events_file):
        try:
            with open(events_file, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"tool.execution_start"' in line:
                        try:
                            evt = json.loads(line)
                            if evt.get("type") == "tool.execution_start":
                                tool_name = evt.get("data", {}).get("toolName", "")
                                if tool_name:
                                    tool_counter[tool_name] += 1
                        except Exception:
                            pass
        except Exception:
            pass
    tool_counts = [{"name": k, "count": v} for k, v in tool_counter.most_common(10)]

    return {
        "checkpoints": [dict(r) for r in checkpoints],
        "refs": [dict(r) for r in refs],
        "turns": [dict(r) for r in reversed(list(turns))],
        "recent_output": get_recent_output(session_id),
        "tool_counts": tool_counts,
        "files": [r["file_path"] for r in files],
    }


@app.get("/api/files", response_model=list[FileEntryResponse])
def api_files():
    """Return most-edited files across all sessions."""
    try:
        db = get_db()
    except FileNotFoundError:
        return []  # No file data without the DB
    try:
        rows = db.execute("""
            SELECT sf.file_path, COUNT(DISTINCT sf.session_id) as session_count,
            GROUP_CONCAT(DISTINCT sf.session_id) as session_ids
            FROM session_files sf GROUP BY sf.file_path
            ORDER BY session_count DESC LIMIT 100
        """).fetchall()
    finally:
        db.close()
    return [dict(r) for r in rows]


@app.get("/api/processes", response_model=dict[str, ProcessResponse])
def api_processes():
    """Return currently running copilot and Claude sessions mapped by session ID."""
    result = {sid: asdict(info) for sid, info in get_running_sessions().items()}
    try:
        claude = get_running_claude_sessions()
        result.update({sid: asdict(info) for sid, info in claude.items()})
    except Exception as e:
        logger.debug("Error getting Claude processes: %s", e)
    return result


@app.post("/api/kill/{session_id:path}", response_model=ActionResponse)
def api_kill(session_id: str):
    """Kill the process for a running session."""
    err = _validate_session_id(session_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    # Check both Copilot and Claude running sessions
    running: dict[str, ProcessInfo] = dict(get_running_sessions())
    try:
        running.update(get_running_claude_sessions())
    except Exception:
        pass

    if session_id not in running:
        return JSONResponse(
            {"success": False, "message": "Session not found among running processes"},
            status_code=404,
        )
    info = running[session_id]
    pid = info.pid
    if not pid:
        return JSONResponse({"success": False, "message": "PID not available"}, status_code=404)
    # Only kill processes whose command line contains "copilot" or "claude"
    cmd_lower = info.cmdline.lower()
    if "copilot" not in cmd_lower and "claude" not in cmd_lower:
        return JSONResponse(
            {"success": False, "message": "Process is not a recognized AI assistant process"},
            status_code=403,
        )
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=True, capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
        return {"success": True, "message": f"Killed PID {pid}"}
    except Exception as e:
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)


@app.post("/api/focus/{session_id:path}", response_model=ActionResponse)
def api_focus(session_id: str):
    """Focus the terminal window for a running session."""
    err = _validate_session_id(session_id)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    success, message = focus_session_window(session_id)
    return {"success": success, "message": message}


@app.get("/api/remote-sessions", response_model=list[SessionResponse])
def api_remote_sessions():
    """Return active sessions from other machines via the sync folder."""
    if not _sync_folder:
        return []
    try:
        return read_remote_sessions(_sync_folder)
    except Exception:
        logger.debug("Failed to read remote sessions", exc_info=True)
        return []


@app.get("/api/server-info", response_model=ServerInfoResponse)
def server_info(request: Request):
    """Return server metadata including PID."""
    from .logging_config import get_log_file, get_log_level

    # Derive port from the ASGI server scope rather than trusting the Host header
    scope = request.scope
    server = scope.get("server")
    port = str(server[1]) if server and len(server) >= 2 else "5111"
    return {
        "pid": os.getpid(),
        "port": port,
        "sync_folder": str(_sync_folder) if _sync_folder else None,
        "log_file": get_log_file(),
        "log_level": get_log_level(),
    }


@app.get("/api/version", response_model=VersionResponse)
def api_version():
    """Return current version and check PyPI for the latest release."""
    now = time.monotonic()
    with _version_lock:
        if (
            _version_cache.latest is not None
            and now - _version_cache.checked_at < VERSION_CACHE_TTL
        ):
            return {
                "current": __version__,
                "latest": _version_cache.latest,
                "update_available": _version_cache.update_available,
            }

    try:
        with urllib.request.urlopen(PYPI_PACKAGE_URL, timeout=PYPI_FETCH_TIMEOUT) as resp:
            data = json.loads(resp.read())

        def _ver(v: str) -> tuple:
            """Parse a PEP 440-ish version into a comparable tuple."""
            m = re.match(r"(\d+(?:\.\d+)*)", v)
            if not m:
                return (0, 0, 0, 0)
            nums = tuple(int(x) for x in m.group(1).split("."))
            # Pre-release (a/b/rc) sorts before the final release
            pre = 0 if re.search(r"(a|b|rc)\d*$", v) else 1
            return (*nums, pre)

        def _is_prerelease(v: str) -> bool:
            return bool(re.search(r"(a|b|rc|dev)\d*$", v))

        if _is_prerelease(__version__):
            latest = max(data.get("releases", {}), key=_ver, default=__version__)
        else:
            latest = data["info"]["version"]

        update_available = _ver(latest) > _ver(__version__)
    except Exception:
        latest = __version__
        update_available = False

    with _version_lock:
        _version_cache.latest = latest
        _version_cache.update_available = update_available
        _version_cache.checked_at = now
    return {
        "current": __version__,
        "latest": latest,
        "update_available": update_available,
    }


@app.post("/api/update", response_model=ActionResponse)
def api_update(request: Request):
    """Spawn a detached subprocess to pip-upgrade the package and restart."""
    scope = request.scope
    server = scope.get("server")
    port = str(server[1]) if server and len(server) >= 2 else "5111"
    server_pid = os.getpid()

    script_lines = [
        "import subprocess, sys, os, signal, time, shutil",
        "time.sleep(2)",
        # Kill the server BEFORE pip upgrade to release file locks and
        # avoid corrupting the pip cache on Windows.
        f"pid = {server_pid}",
        "try:",
        "    if sys.platform == 'win32':",
        "        subprocess.run(['taskkill', '/F', '/PID', str(pid)], capture_output=True, check=False)",
        "    else:",
        "        os.kill(pid, signal.SIGTERM)",
        "except Exception:",
        "    pass",
        "time.sleep(1)",
        "subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-cache-dir',"
        " '--upgrade', 'ghcp-cli-dashboard'],"
        " check=False, capture_output=True)",
        "cmd = shutil.which('copilot-dashboard')",
        "if cmd:",
        "    kw = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}",
        "    if sys.platform == 'win32':",
        "        kw['creationflags'] = subprocess.CREATE_NO_WINDOW | 0x8",
        "    else:",
        "        kw['start_new_session'] = True",
        f"    subprocess.Popen([cmd, 'start', '--background', '--port', '{port}'], **kw)",
    ]
    script = "\n".join(script_lines)

    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True

    subprocess.Popen([sys.executable, "-c", script], **kwargs)
    return {
        "success": True,
        "message": "Update started. Server will restart shortly.",
    }


# ── Autostart ───────────────────────────────────────────────────────────────

_AUTOSTART_VALUE_NAME = "CopilotDashboard"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _is_autostart_enabled() -> bool:
    """Check if the HKCU Run registry value exists."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _AUTOSTART_VALUE_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


@app.get("/api/autostart", response_model=AutostartStatusResponse)
def api_autostart_status():
    """Check whether autostart is supported on this platform and currently enabled."""
    supported = sys.platform == "win32"
    enabled = _is_autostart_enabled() if supported else False
    return {"supported": supported, "enabled": enabled}


@app.post("/api/autostart/enable", response_model=ActionResponse)
def api_autostart_enable(request: Request):
    """Enable autostart via the Windows HKCU Run registry key."""
    if sys.platform != "win32":
        return {"success": False, "message": "Autostart is only supported on Windows."}

    import shutil
    import winreg

    scope = request.scope
    server = scope.get("server")
    port = str(server[1]) if server and len(server) >= 2 else "5111"

    cmd = shutil.which("copilot-dashboard")
    if cmd:
        cmd_str = f'"{cmd}" start --background --port {port}'
    else:
        cmd_str = f'"{sys.executable}" -m src.session_dashboard start --background --port {port}'

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _AUTOSTART_VALUE_NAME, 0, winreg.REG_SZ, cmd_str)
        return {"success": True, "message": "Autostart enabled."}
    except OSError as e:
        return {"success": False, "message": f"Failed: {e}"}


@app.post("/api/autostart/disable", response_model=ActionResponse)
def api_autostart_disable():
    """Disable autostart by removing the Windows HKCU Run registry value."""
    if sys.platform != "win32":
        return {"success": False, "message": "Autostart is only supported on Windows."}

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _AUTOSTART_VALUE_NAME)
        return {"success": True, "message": "Autostart disabled."}
    except FileNotFoundError:
        return {"success": True, "message": "Autostart was already disabled."}
    except OSError as e:
        return {"success": False, "message": f"Failed: {e}"}


# ── Settings (sync toggle) ──────────────────────────────────────────────────


def _read_dashboard_config() -> dict:
    """Read the full dashboard-config.json, returning {} on error."""
    if not os.path.exists(DASHBOARD_CONFIG_PATH):
        return {}
    try:
        with open(DASHBOARD_CONFIG_PATH, encoding="utf-8") as f:
            result: dict = json.load(f)
            return result
    except Exception:
        return {}


def _write_dashboard_config(cfg: dict) -> None:
    """Write dashboard-config.json atomically."""
    os.makedirs(os.path.dirname(DASHBOARD_CONFIG_PATH), exist_ok=True)
    tmp = DASHBOARD_CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, DASHBOARD_CONFIG_PATH)


def _reload_sync_folder() -> None:
    """Re-resolve the sync folder after a settings change."""
    global _sync_folder
    _sync_folder = resolve_sync_folder()


@app.get("/api/settings", response_model=SettingsResponse)
def api_get_settings():
    """Return current dashboard settings."""
    from .logging_config import get_log_level

    cfg = _read_dashboard_config()
    sync_cfg = cfg.get("sync", {})
    sync_enabled = sync_cfg.get("enabled", True) if isinstance(sync_cfg, dict) else True
    return {"sync_enabled": sync_enabled, "log_level": get_log_level()}


@app.put("/api/settings", response_model=SettingsResponse)
async def api_put_settings(request: Request):
    """Update dashboard settings."""
    from .logging_config import get_log_level, set_log_level

    body = await request.json()
    cfg = _read_dashboard_config()

    if "sync_enabled" in body:
        if "sync" not in cfg or not isinstance(cfg.get("sync"), dict):
            cfg["sync"] = {}
        cfg["sync"]["enabled"] = bool(body["sync_enabled"])

    if "log_level" in body:
        level = str(body["log_level"]).upper()
        if level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            set_log_level(level)
            if "logging" not in cfg or not isinstance(cfg.get("logging"), dict):
                cfg["logging"] = {}
            cfg["logging"]["level"] = level

    _write_dashboard_config(cfg)
    _reload_sync_folder()

    sync_cfg = cfg.get("sync", {})
    sync_enabled = sync_cfg.get("enabled", True) if isinstance(sync_cfg, dict) else True
    return {"sync_enabled": sync_enabled, "log_level": get_log_level()}


# ── PWA / static routes ─────────────────────────────────────────────────────


@app.get("/favicon.png", include_in_schema=False)
def favicon():
    """Serve the Copilot favicon."""
    path = os.path.join(STATIC_DIR, "favicon.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return Response(status_code=404)


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    """PWA web app manifest — enables 'Install app' in Chrome/Edge."""
    data = {
        "name": "Copilot Dashboard",
        "short_name": "Copilot",
        "description": "Monitor all your GitHub Copilot CLI sessions in real-time.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#0d1117",
        "theme_color": "#0d1117",
        "icons": [
            {"src": "/favicon.png", "sizes": "64x64", "type": "image/png"},
            {
                "src": "/static/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable",
            },
            {
                "src": "/static/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable",
            },
        ],
    }
    return JSONResponse(data)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Minimal service worker required for PWA installability."""
    return Response(
        content="self.addEventListener('fetch', () => {});",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/", include_in_schema=False)
def index():
    """Serve the React SPA or fall back to the legacy template.

    Injects the API token into the page so the frontend can authenticate.
    """
    token_script = f'<script>window.__DASHBOARD_TOKEN__="{API_TOKEN}";</script>'

    # Prefer the React build if it exists
    dist_index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(dist_index):
        with open(dist_index, encoding="utf-8") as f:
            html = f.read()
        # Inject token before closing </head> tag
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(html)
    # Fall back to legacy Jinja2 template
    template_path = os.path.join(TEMPLATES_DIR, "dashboard.html")
    if os.path.exists(template_path):
        with open(template_path, encoding="utf-8") as f:
            html = f.read().replace("{{ version }}", __version__)
        html = html.replace("</head>", f"{token_script}</head>", 1)
        return HTMLResponse(html)
    return HTMLResponse(
        f"<html><head>{token_script}</head><body>"
        "<h1>Copilot Dashboard</h1><p>No frontend build found.</p></body></html>"
    )


# Serve React build assets (JS, CSS, etc.) at root level so Vite's
# relative imports work (e.g. /assets/index-abc123.js)
if os.path.isdir(DIST_DIR):
    app.mount(
        "/assets", StaticFiles(directory=os.path.join(DIST_DIR, "assets")), name="dist-assets"
    )
