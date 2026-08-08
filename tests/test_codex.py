"""Tests for the Codex rollout reader."""

import json
import os
import time
from unittest.mock import patch

from src.codex import (
    SESSION_ID_PREFIX,
    get_codex_session_cwd,
    get_codex_session_detail,
    get_codex_sessions,
    get_running_codex_sessions,
)
from src.models import ProcessInfo


def _write_rollout(root, *, complete: bool = True):
    path = root / "2026" / "08" / "08" / "rollout-rollout-abc.jsonl"
    path.parent.mkdir(parents=True)
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": "rollout-abc",
                "session_id": "thread-123",
                "timestamp": "2026-08-08T12:00:00Z",
                "cwd": "/Users/test/agenteye-demo",
                "git": {
                    "branch": "feat/codex",
                    "repository_url": "https://github.com/acme/demo.git",
                },
            },
        },
        {
            "type": "response_item",
            "payload": {
                "id": "user-1",
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "Add Codex support"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "exec",
                "arguments": '{"cmd":"touch src/codex.py"}',
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "type": "patch_apply_end",
                "changes": [{"path": "src/codex.py"}],
            },
        },
        {
            "type": "response_item",
            "payload": {
                "id": "assistant-1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Implemented."}],
            },
        },
        {"type": "event_msg", "payload": {"type": "task_started"}},
    ]
    if complete:
        records.append({"type": "event_msg", "payload": {"type": "task_complete"}})
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    return path


def test_reads_codex_session_metadata(tmp_path):
    root = tmp_path / "sessions"
    _write_rollout(root)
    running = {
        f"{SESSION_ID_PREFIX}thread-123": ProcessInfo(
            pid=0,
            state="idle",
            waiting_context="Session idle — waiting for user message",
        )
    }

    with patch("src.codex.CODEX_SESSIONS_DIR", str(root)):
        sessions = get_codex_sessions(running=running)

    assert len(sessions) == 1
    session = sessions[0]
    assert session["id"] == f"{SESSION_ID_PREFIX}thread-123"
    assert session["source"] == "codex"
    assert session["summary"] == "Add Codex support"
    assert session["cwd"] == "/Users/test/agenteye-demo"
    assert session["repository"] == "demo"
    assert session["branch"] == "feat/codex"
    assert session["restart_cmd"].endswith("codex resume thread-123")
    assert session["is_running"] is True
    assert session["state"] == "idle"


def test_parses_codex_detail(tmp_path):
    root = tmp_path / "sessions"
    _write_rollout(root)

    with patch("src.codex.CODEX_SESSIONS_DIR", str(root)):
        detail = get_codex_session_detail("thread-123")

    assert detail["turns"] == [
        {
            "turn_index": 0,
            "user_message": "Add Codex support",
            "assistant_response": "Implemented.",
        }
    ]
    assert detail["tool_counts"] == [{"name": "exec", "count": 1}]
    assert detail["files"] == ["src/codex.py"]
    assert detail["recent_output"] == ["Implemented."]


def test_recent_incomplete_rollout_is_running(tmp_path):
    root = tmp_path / "sessions"
    path = _write_rollout(root, complete=False)
    now = time.time()
    os.utime(path, (now, now))

    with patch("src.codex.CODEX_SESSIONS_DIR", str(root)):
        running = get_running_codex_sessions()

    proc = running[f"{SESSION_ID_PREFIX}thread-123"]
    assert proc.pid == 0
    assert proc.state == "working"


def test_codex_cwd_and_missing_root(tmp_path):
    root = tmp_path / "sessions"
    _write_rollout(root)
    with patch("src.codex.CODEX_SESSIONS_DIR", str(root)):
        assert get_codex_session_cwd("thread-123") == "/Users/test/agenteye-demo"
    with patch("src.codex.CODEX_SESSIONS_DIR", str(tmp_path / "missing")):
        assert get_codex_sessions() == []
