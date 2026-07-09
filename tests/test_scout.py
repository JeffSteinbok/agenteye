"""Tests for Microsoft Scout session support."""

import json
import os
import sqlite3
from datetime import UTC, datetime

from src.models import ProcessInfo
from src.scout import (
    SESSION_ID_PREFIX,
    get_recent_scout_output,
    get_running_scout_sessions,
    get_scout_session_cwd,
    get_scout_session_detail,
    get_scout_sessions,
)


def _create_scout_db(path: str) -> None:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            cwd TEXT,
            repository TEXT,
            branch TEXT,
            summary TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE turns (
            session_id TEXT,
            turn_index INTEGER,
            user_message TEXT,
            assistant_response TEXT
        );
        CREATE TABLE session_files (
            session_id TEXT,
            file_path TEXT,
            tool_name TEXT
        );
        CREATE TABLE checkpoints (
            session_id TEXT,
            checkpoint_number INTEGER,
            title TEXT,
            overview TEXT,
            next_steps TEXT
        );
        CREATE TABLE session_refs (
            session_id TEXT,
            ref_type TEXT,
            ref_value TEXT
        );
    """)
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
        (
            "scout-1111",
            "C:\\Users\\test\\ScoutRepo",
            "owner/scout-repo",
            "main",
            "Scout task",
            "2026-07-08T18:00:00Z",
            "2026-07-08T18:10:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?,?,?)",
        ("scout-1111", 0, "Do Scout work", "Done"),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?,?,?)",
        ("scout-1111", "src/app.py", "edit"),
    )
    conn.commit()
    conn.close()


def _write_events(root: str, session_id: str, events: list[dict]) -> None:
    session_dir = os.path.join(root, session_id)
    os.makedirs(session_dir, exist_ok=True)
    with open(os.path.join(session_dir, "events.jsonl"), "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")


def test_get_scout_sessions_reads_embedded_copilot_store(monkeypatch, tmp_path):
    db_path = str(tmp_path / "session-store.db")
    state_dir = str(tmp_path / "session-state")
    _create_scout_db(db_path)
    _write_events(
        state_dir,
        "scout-1111",
        [
            {
                "type": "session.start",
                "timestamp": "2026-07-08T18:00:00Z",
                "data": {
                    "context": {
                        "cwd": "C:\\Users\\test\\ScoutRepo",
                        "branch": "feature/scout",
                        "repository": "owner/scout-repo",
                    }
                },
            },
            {
                "type": "tool.execution_complete",
                "timestamp": "2026-07-08T18:05:00Z",
                "data": {"result": {"content": "output"}},
            },
            {"type": "assistant.turn_end", "timestamp": "2026-07-08T18:10:00Z", "data": {}},
        ],
    )
    running = {f"{SESSION_ID_PREFIX}scout-1111": ProcessInfo(pid=0, state="idle")}
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STORE_DB", db_path)
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STATE_DIR", state_dir)

    sessions = get_scout_sessions(running=running)

    assert len(sessions) == 1
    session = sessions[0]
    assert session["id"] == f"{SESSION_ID_PREFIX}scout-1111"
    assert session["source"] == "scout"
    assert session["is_running"] is True
    assert session["branch"] == "feature/scout"
    assert session["restart_cmd"] == 'cd "C:\\Users\\test\\ScoutRepo" && scout --resume scout-1111'


def test_running_scout_sessions_use_recent_event_mtime(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "session-state")
    _write_events(
        state_dir,
        "active-1111",
        [
            {"type": "session.start", "timestamp": datetime.now(UTC).isoformat(), "data": {}},
            {"type": "assistant.turn_end", "timestamp": datetime.now(UTC).isoformat(), "data": {}},
        ],
    )
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STATE_DIR", state_dir)

    running = get_running_scout_sessions()

    assert f"{SESSION_ID_PREFIX}active-1111" in running
    assert running[f"{SESSION_ID_PREFIX}active-1111"].state == "idle"
    assert running[f"{SESSION_ID_PREFIX}active-1111"].pid == 0


def test_scout_detail_reads_db_and_recent_output(monkeypatch, tmp_path):
    db_path = str(tmp_path / "session-store.db")
    state_dir = str(tmp_path / "session-state")
    _create_scout_db(db_path)
    _write_events(
        state_dir,
        "scout-1111",
        [
            {"type": "tool.execution_start", "data": {"toolName": "read_file"}},
            {
                "type": "tool.execution_complete",
                "data": {"result": {"content": "line one\nline two"}},
            },
        ],
    )
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STORE_DB", db_path)
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STATE_DIR", state_dir)

    detail = get_scout_session_detail(f"{SESSION_ID_PREFIX}scout-1111")

    assert detail["turns"][0]["user_message"] == "Do Scout work"
    assert detail["files"] == ["src/app.py"]
    assert detail["tool_counts"] == [{"name": "read_file", "count": 1}]
    assert get_recent_scout_output("scout-1111") == ["line one", "line two"]
    assert get_scout_session_cwd("scout-1111") == "C:\\Users\\test\\ScoutRepo"
