"""Codex desktop/CLI session reader for Agent Eye.

Codex stores local rollout transcripts as JSONL files below
``~/.codex/sessions/YYYY/MM/DD``.  This reader deliberately treats those
files as read-only: it exposes session metadata, recent conversation details,
and a resume command, but it does not attempt to focus or terminate the Codex
desktop process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shlex
import time
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from .constants import CODEX_SESSIONS_DIR, MTIME_ACTIVE_THRESHOLD
from .grouping import get_group_name
from .models import ProcessInfo

logger = logging.getLogger(__name__)

SESSION_ID_PREFIX = "codex:"
_SAFE_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_HEAD_BYTES = 64 * 1024
_TAIL_BYTES = 128 * 1024
_MAX_SUMMARY_LEN = 200
_MAX_OUTPUT_LEN = 1000
_PATH_KEYS = frozenset({"path", "file_path", "filePath", "filename"})

# Cache snapshots by path and file identity.  Most Codex history is immutable;
# this avoids rereading gigabytes of old transcripts on every dashboard poll.
_snapshot_cache: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _time_ago(iso_str: str | None) -> str:
    """Convert an ISO timestamp to a compact relative time string."""
    if not iso_str:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        seconds = max(0, int((datetime.now(UTC) - dt).total_seconds()))
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except (TypeError, ValueError):
        return iso_str or "unknown"


def _iso_from_mtime(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, tz=UTC).isoformat()


def _decode_records(raw: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _read_head_and_tail(path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read bounded transcript slices without loading a large rollout file."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            head = handle.read(_HEAD_BYTES)
            if size <= _HEAD_BYTES + _TAIL_BYTES:
                return _decode_records(head + handle.read()), []
            handle.seek(max(0, size - _TAIL_BYTES))
            tail = handle.read(_TAIL_BYTES)
        # The first tail line may be truncated because the read begins in the
        # middle of a JSONL record.
        newline = tail.find(b"\n")
        if newline >= 0:
            tail = tail[newline + 1 :]
        return _decode_records(head), _decode_records(tail)
    except OSError:
        return [], []


def _snapshot(path: str) -> dict[str, Any] | None:
    try:
        stat = os.stat(path)
    except OSError:
        return None

    cache_key = (stat.st_mtime_ns, stat.st_size)
    cached = _snapshot_cache.get(path)
    if cached and cached[:2] == cache_key:
        return cached[2]

    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            first = json.loads(handle.readline())
    except (OSError, json.JSONDecodeError):
        return None

    meta = first.get("payload", {}) if isinstance(first, dict) else {}
    if first.get("type") != "session_meta" or not isinstance(meta, dict):
        return None

    raw_id = meta.get("session_id") or meta.get("id") or os.path.basename(path)
    raw_id = str(raw_id).removeprefix("rollout-")
    if not _SAFE_SESSION_ID_RE.match(raw_id):
        return None

    head, tail = _read_head_and_tail(path)
    value = {
        "path": path,
        "meta": meta,
        "session_id": raw_id,
        "mtime": stat.st_mtime,
        "created_at": str(meta.get("timestamp") or _iso_from_mtime(stat.st_ctime)),
        "head": head,
        "tail": tail,
    }
    _snapshot_cache[path] = (stat.st_mtime_ns, stat.st_size, value)
    return value


def _iter_snapshots() -> list[dict[str, Any]]:
    if not os.path.isdir(CODEX_SESSIONS_DIR):
        return []
    snapshots: list[dict[str, Any]] = []
    for root, _dirs, files in os.walk(CODEX_SESSIONS_DIR):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            item = _snapshot(os.path.join(root, name))
            if item is not None:
                snapshots.append(item)
    return snapshots


def _group_snapshots() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in _iter_snapshots():
        grouped.setdefault(item["session_id"], []).append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item["mtime"])
    return grouped


def _records(item: dict[str, Any], *, recent: bool = False) -> list[dict[str, Any]]:
    return item["tail"] if recent and item["tail"] else item["head"] + item["tail"]


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in {"input_text", "output_text", "text"}:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _message_text(payload: dict[str, Any]) -> str:
    return _text_from_content(payload.get("content"))


def _first_user_text(items: list[dict[str, Any]]) -> str:
    for item in items:
        for record in item["head"]:
            if record.get("type") != "response_item":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or payload.get("type") != "message":
                continue
            if payload.get("role") != "user":
                continue
            text = _message_text(payload)
            if text:
                return text[:_MAX_SUMMARY_LEN]
    return ""


def _repository_from_meta(meta: dict[str, Any], cwd: str) -> str:
    git = meta.get("git")
    if isinstance(git, dict):
        url = git.get("repository_url")
        if isinstance(url, str) and url:
            value = url.rstrip("/").rsplit("/", 1)[-1]
            return value.removesuffix(".git")
    return os.path.basename(cwd) if cwd else ""


def _build_restart_cmd(session_id: str, cwd: str) -> str:
    parts: list[str] = []
    if cwd:
        parts.append(f"cd {shlex.quote(cwd)} &&")
    parts.append(f"codex resume {shlex.quote(session_id)}")
    return " ".join(parts)


def _latest_event(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    records = _records(item, recent=True)
    for record in reversed(records):
        payload = record.get("payload")
        if record.get("type") == "event_msg" and isinstance(payload, dict):
            return str(payload.get("type") or ""), payload
    return "", {}


def _state_for_item(item: dict[str, Any]) -> tuple[str, str]:
    event_type, payload = _latest_event(item)
    if event_type == "task_complete":
        return "idle", "Session idle — waiting for user message"
    if event_type == "turn_aborted":
        return "idle", "Session idle — waiting for user message"
    if event_type == "user_message":
        return "working", ""
    if event_type in {"task_started", "agent_reasoning", "sub_agent_activity"}:
        return "working", ""
    for record in reversed(_records(item, recent=True)):
        if record.get("type") == "response_item":
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("type") in {
                "function_call",
                "custom_tool_call",
                "web_search_call",
                "tool_search_call",
            }:
                return "working", ""
    return "working", ""


def _turn_count(items: list[dict[str, Any]]) -> int:
    count = 0
    for item in items:
        for record in _records(item):
            if record.get("type") != "response_item":
                continue
            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("type") == "message":
                if payload.get("role") == "user" and _message_text(payload):
                    count += 1
    return count


def _last_assistant_text(item: dict[str, Any]) -> str:
    for record in reversed(_records(item, recent=True)):
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        if payload.get("role") != "assistant":
            continue
        text = _message_text(payload)
        if text:
            return text[:_MAX_OUTPUT_LEN]
    return ""


def get_running_codex_sessions() -> dict[str, ProcessInfo]:
    """Return recently updated Codex sessions with best-effort state."""
    now = time.time()
    result: dict[str, ProcessInfo] = {}
    for session_id, items in _group_snapshots().items():
        latest = items[-1]
        if now - latest["mtime"] > MTIME_ACTIVE_THRESHOLD:
            continue
        state, waiting_context = _state_for_item(latest)
        result[SESSION_ID_PREFIX + session_id] = ProcessInfo(
            pid=0,
            cmdline="Codex desktop/CLI session file",
            state=state,
            waiting_context=waiting_context,
        )
    return result


def get_codex_sessions(
    running: dict[str, ProcessInfo] | None = None,
) -> list[dict[str, Any]]:
    """Read Codex rollout metadata and return dashboard-compatible sessions."""
    if running is None:
        running = get_running_codex_sessions()

    sessions: list[dict[str, Any]] = []
    for session_id, items in _group_snapshots().items():
        latest = items[-1]
        first = items[0]
        meta = first["meta"]
        cwd = str(meta.get("cwd") or "")
        git = meta.get("git") if isinstance(meta.get("git"), dict) else {}
        branch = str(git.get("branch") or "")
        created_at = str(meta.get("timestamp") or first["created_at"])
        updated_at = _iso_from_mtime(latest["mtime"])
        prefixed_id = SESSION_ID_PREFIX + session_id
        proc = running.get(prefixed_id)
        summary = _first_user_text(items) or "Codex session"
        session: dict[str, Any] = {
            "id": prefixed_id,
            "cwd": cwd,
            "repository": _repository_from_meta(meta, cwd),
            "branch": branch,
            "summary": summary,
            "created_at": created_at,
            "updated_at": updated_at,
            "created_ago": _time_ago(created_at),
            "time_ago": _time_ago(updated_at),
            "turn_count": _turn_count(items),
            "file_count": 0,
            "checkpoint_count": 0,
            "is_running": proc is not None,
            "state": proc.state if proc else None,
            "waiting_context": proc.waiting_context if proc else "",
            "bg_tasks": 0,
            "recent_activity": _last_assistant_text(latest),
            "restart_cmd": _build_restart_cmd(session_id, cwd),
            "mcp_servers": [],
            "tool_calls": 0,
            "subagent_runs": 0,
            "intent": "",
            "source": "codex",
        }
        session["group"] = get_group_name(session)
        sessions.append(session)
    return sessions


def _iter_detail_records(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in items:
        records.extend(_records(item))
    return records


def _collect_paths(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _PATH_KEYS and isinstance(child, str):
                candidate = child.strip()
                if candidate and "\n" not in candidate and len(candidate) <= 500:
                    found.add(candidate)
            elif key in {"changes", "input", "arguments"}:
                _collect_paths(child, found)
    elif isinstance(value, list):
        for child in value:
            _collect_paths(child, found)
    elif isinstance(value, str) and value[:1] in "[{":
        try:
            _collect_paths(json.loads(value), found)
        except json.JSONDecodeError:
            pass


def get_codex_session_detail(session_id: str) -> dict[str, Any]:
    """Return recent conversation, tool, and changed-file details."""
    raw_id = session_id.removeprefix(SESSION_ID_PREFIX)
    if not _SAFE_SESSION_ID_RE.match(raw_id):
        return {"checkpoints": [], "refs": [], "turns": [], "recent_output": [], "tool_counts": [], "files": []}

    items = _group_snapshots().get(raw_id, [])
    if not items:
        return {"checkpoints": [], "refs": [], "turns": [], "recent_output": [], "tool_counts": [], "files": []}

    turns: list[dict[str, Any]] = []
    recent_output: list[str] = []
    tool_counter: Counter[str] = Counter()
    files_seen: set[str] = set()
    turn_index = 0

    for record in _iter_detail_records(items):
        record_type = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue

        if record_type == "response_item":
            response_type = payload.get("type")
            if response_type == "message":
                text = _message_text(payload)
                if not text:
                    continue
                role = payload.get("role")
                if role == "user":
                    turns.append(
                        {
                            "turn_index": turn_index,
                            "user_message": text,
                            "assistant_response": None,
                        }
                    )
                    turn_index += 1
                elif role == "assistant":
                    recent_output.append(text[:_MAX_OUTPUT_LEN])
                    if turns and turns[-1]["assistant_response"] is None:
                        turns[-1]["assistant_response"] = text
                    else:
                        turns.append(
                            {
                                "turn_index": turn_index,
                                "user_message": None,
                                "assistant_response": text,
                            }
                        )
                        turn_index += 1
            elif response_type in {
                "function_call",
                "custom_tool_call",
                "web_search_call",
                "tool_search_call",
            }:
                name = payload.get("name") or response_type
                tool_counter[str(name)] += 1
                _collect_paths(payload.get("arguments"), files_seen)
                _collect_paths(payload.get("input"), files_seen)
        elif record_type == "event_msg":
            if payload.get("type") == "patch_apply_end":
                _collect_paths(payload.get("changes"), files_seen)

    return {
        "checkpoints": [],
        "refs": [],
        "turns": turns[-10:],
        "recent_output": recent_output[-10:],
        "tool_counts": [{"name": name, "count": count} for name, count in tool_counter.most_common(10)],
        "files": sorted(files_seen),
    }


def get_codex_session_cwd(session_id: str) -> str | None:
    raw_id = session_id.removeprefix(SESSION_ID_PREFIX)
    items = _group_snapshots().get(raw_id, [])
    if not items:
        return None
    cwd = items[0]["meta"].get("cwd")
    return str(cwd) if isinstance(cwd, str) and cwd else None
