"""Shared pytest fixtures for the test suite."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.dashboard_api import API_TOKEN, app


@pytest.fixture
def client():
    """TestClient that automatically includes the API auth token."""
    real_client = TestClient(app)
    original_get = real_client.get
    original_post = real_client.post
    original_put = real_client.put

    def _authed_get(url, **kwargs):
        params = kwargs.pop("params", {}) or {}
        params["token"] = API_TOKEN
        return original_get(url, params=params, **kwargs)

    def _authed_post(url, **kwargs):
        params = kwargs.pop("params", {}) or {}
        params["token"] = API_TOKEN
        return original_post(url, params=params, **kwargs)

    def _authed_put(url, **kwargs):
        params = kwargs.pop("params", {}) or {}
        params["token"] = API_TOKEN
        return original_put(url, params=params, **kwargs)

    real_client.get = _authed_get  # type: ignore[assignment]
    real_client.post = _authed_post  # type: ignore[assignment]
    real_client.put = _authed_put  # type: ignore[assignment]
    return real_client


@pytest.fixture(autouse=True)
def isolate_scout_storage(monkeypatch, tmp_path):
    """Keep tests from reading the developer's real ~/.scout sessions."""
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STATE_DIR", str(tmp_path / "no-scout-state"))
    monkeypatch.setattr("src.scout.SCOUT_SESSION_STORE_DB", str(tmp_path / "no-scout.db"))


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
