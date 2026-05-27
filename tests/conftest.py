"""Shared pytest fixtures for the test suite."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.dashboard_api import API_TOKEN, app


@pytest.fixture
def client():
    """TestClient that automatically sends `Authorization: Bearer <token>`.

    This mirrors what the production frontend does. A separate test elsewhere
    exercises the legacy `?token=` query-string path for backwards
    compatibility.
    """
    real_client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})
    return real_client


@pytest.fixture
def events_dir(tmp_path):
    """Create a temporary events directory structure."""
    return tmp_path


def write_events(events_dir, session_id, events):
    """Write a list of event dicts to a session's events.jsonl file."""
    session_dir = events_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    events_file = session_dir / "events.jsonl"
    with open(events_file, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
    return str(events_file)


@pytest.fixture
def make_events(events_dir):
    """Fixture that returns a helper to write events.jsonl files."""

    def _make(session_id, events):
        return write_events(events_dir, session_id, events)

    return _make


@pytest.fixture
def mock_db(tmp_path):
    """Create an in-memory SQLite DB with the session store schema."""
    db_path = tmp_path / "session-store.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
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
    conn.commit()
    yield conn, str(db_path)
    conn.close()
