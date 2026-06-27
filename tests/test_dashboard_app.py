"""Tests for dashboard_api.py — pure helper functions and FastAPI routes."""

import json
import os
import signal
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from src.dashboard_api import (
    build_restart_command,
    get_recent_activity,
    time_ago,
)
from src.grouping import get_group_name
from src.models import EventData, ProcessInfo


# ---------------------------------------------------------------------------
# time_ago
# ---------------------------------------------------------------------------


class TestTimeAgo:
    def test_empty_string(self):
        assert time_ago("") == "unknown"

    def test_none(self):
        assert time_ago(None) == "unknown"

    def test_invalid_string(self):
        result = time_ago("not-a-date")
        assert result == "not-a-date"

    def test_seconds_ago(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
        assert time_ago(ts) == "30s ago"

    def test_minutes_ago(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        assert time_ago(ts) == "5m ago"

    def test_hours_ago(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        assert time_ago(ts) == "3h ago"

    def test_days_ago(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        assert time_ago(ts) == "2d ago"

    def test_z_suffix(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = time_ago(ts)
        assert result.endswith("s ago")

    def test_exactly_one_minute(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
        assert time_ago(ts) == "1m ago"

    def test_exactly_one_hour(self):
        from datetime import UTC, datetime, timedelta

        ts = (datetime.now(UTC) - timedelta(seconds=3600)).isoformat()
        assert time_ago(ts) == "1h ago"


# ---------------------------------------------------------------------------
# get_group_name
# ---------------------------------------------------------------------------


class TestGetGroupName:
    def _session(self, cwd="", summary="", first_msg="", last_cp_overview="", repository=""):
        return {
            "cwd": cwd,
            "summary": summary,
            "first_msg": first_msg,
            "last_cp_overview": last_cp_overview,
            "repository": repository,
        }

    def test_repository_field_used(self):
        s = self._session(repository="owner/my-project")
        assert get_group_name(s) == "my-project"

    def test_repository_without_owner(self):
        s = self._session(repository="standalone-repo")
        assert get_group_name(s) == "standalone-repo"

    def test_cwd_last_segment(self):
        s = self._session(cwd="/src/MyProject/feature")
        assert get_group_name(s) == "feature"

    def test_cwd_skips_common_dirs(self):
        s = self._session(cwd="/Users/home/src")
        assert get_group_name(s) == "General"

    def test_repository_takes_priority_over_cwd(self):
        s = self._session(cwd="/some/path/foo", repository="org/bar")
        assert get_group_name(s) == "bar"

    def test_dashboard_keyword(self):
        s = self._session(summary="Improve session dashboard UI")
        assert get_group_name(s) == "Session Dashboard"

    def test_code_review_keyword(self):
        s = self._session(summary="Implement code review feature")
        assert get_group_name(s) == "PR Reviews"

    def test_pipeline_keyword(self):
        s = self._session(summary="Fix build pipeline issue")
        assert get_group_name(s) == "CI/CD Pipelines"

    def test_prune_keyword(self):
        s = self._session(first_msg="Prune stale branches from remote")
        assert get_group_name(s) == "Branch Cleanup"

    def test_cwd_last_segment_fallback(self):
        s = self._session(cwd="C:/Users/homer/MyRepo")
        assert get_group_name(s) == "MyRepo"

    def test_no_cwd_no_keywords_returns_general(self):
        s = self._session()
        assert get_group_name(s) == "General"

    def test_windows_backslash_cwd(self):
        s = self._session(cwd="C:\\Users\\homer\\MyProject")
        assert get_group_name(s) == "MyProject"

    def test_spec_keyword(self):
        s = self._session(summary="Write specification document")
        assert get_group_name(s) == "Specifications"


# ---------------------------------------------------------------------------
# get_recent_activity
# ---------------------------------------------------------------------------


class TestGetRecentActivity:
    def _session(self, last_cp_title="", last_cp_overview="", summary=""):
        return {
            "last_cp_title": last_cp_title,
            "last_cp_overview": last_cp_overview,
            "summary": summary,
        }

    def test_returns_checkpoint_title_when_different_from_summary(self):
        s = self._session(last_cp_title="Fixed the bug", summary="Initial work")
        assert get_recent_activity(s) == "Fixed the bug"

    def test_skips_title_when_same_as_summary(self):
        s = self._session(
            last_cp_title="Same as summary",
            summary="Same as summary",
            last_cp_overview="Some detailed overview. More text here.",
        )
        result = get_recent_activity(s)
        assert result == "Some detailed overview"

    def test_returns_first_sentence_of_overview(self):
        s = self._session(last_cp_overview="First sentence. Second sentence. Third.")
        assert get_recent_activity(s) == "First sentence"

    def test_truncates_long_overview(self):
        long_text = "A" * 130
        s = self._session(last_cp_overview=long_text)
        result = get_recent_activity(s)
        assert len(result) == 120
        assert result.endswith("...")

    def test_returns_empty_when_no_data(self):
        s = self._session()
        assert get_recent_activity(s) == ""

    def test_none_values_handled(self):
        s = {"last_cp_title": None, "last_cp_overview": None, "summary": None}
        assert get_recent_activity(s) == ""


# ---------------------------------------------------------------------------
# build_restart_command
# ---------------------------------------------------------------------------


class TestBuildRestartCommand:
    def _session(self, session_id, cwd=""):
        return {"id": session_id, "cwd": cwd}

    def test_without_cwd(self):
        s = self._session("abc-123")
        assert build_restart_command(s) == "copilot --resume abc-123"

    def test_with_cwd(self):
        s = self._session("abc-123", cwd="/home/user/project")
        cmd = build_restart_command(s)
        assert 'cd "/home/user/project"' in cmd
        assert "copilot --resume abc-123" in cmd

    def test_yolo_flag(self):
        s = self._session("abc-123")
        cmd = build_restart_command(s, yolo=True)
        assert cmd == "copilot --resume abc-123 --yolo"

    def test_yolo_with_cwd(self):
        s = self._session("abc-123", cwd="/project")
        cmd = build_restart_command(s, yolo=True)
        assert "--yolo" in cmd
        assert "copilot --resume abc-123" in cmd


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@pytest.fixture
def populated_db(mock_db):
    conn, db_path = mock_db
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
        ("sess-1", "/project", "owner/repo", "main", "Test session", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO turns VALUES (?,?,?,?)",
        ("sess-1", 0, "Hello world", "Hi there"),
    )
    conn.execute(
        "INSERT INTO checkpoints VALUES (?,?,?,?,?)",
        ("sess-1", 1, "Checkpoint 1", "Overview text.", "Next steps."),
    )
    conn.execute(
        "INSERT INTO session_files VALUES (?,?,?)",
        ("sess-1", "src/foo.py", "edit"),
    )
    conn.execute(
        "INSERT INTO session_refs VALUES (?,?,?)",
        ("sess-1", "pr", "42"),
    )
    conn.commit()
    return conn, db_path


class TestIndexRoute:
    def test_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200


class TestApiSessions:
    def test_returns_session_list(self, client, populated_db):
        _conn, db_path = populated_db
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["id"] == "sess-1"

    def test_returns_empty_when_db_and_events_missing(self, client, tmp_path):
        missing = str(tmp_path / "nonexistent.db")
        with (
            patch("src.dashboard_api.DB_PATH", missing),
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path / "no-sessions")),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        # With no Copilot DB, no events, and no Claude sessions, we get an empty list
        assert resp.status_code == 200
        assert resp.json() == []

    def test_running_session_enriched(self, client, populated_db):
        _conn, db_path = populated_db
        running = {
            "sess-1": ProcessInfo(
                pid=1234,
                state="working",
                waiting_context="",
                bg_tasks=0,
                yolo=True,
                mcp_servers=["github"],
            )
        }
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_running_sessions", return_value=running),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        data = resp.json()
        session = data[0]
        assert session["is_running"] is True
        assert session["state"] == "working"
        assert "--yolo" in session["restart_cmd"]

    def test_filters_dismissed_sessions(self, client, populated_db):
        _conn, db_path = populated_db
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api._read_dashboard_config", return_value={"hidden_sessions": ["sess-1"]}),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []


class TestApiSessionDetail:
    def test_returns_detail(self, client, populated_db):
        _conn, db_path = populated_db
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_recent_output", return_value=["line1"]),
        ):
            resp = client.get("/api/session/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert "checkpoints" in data
        assert "refs" in data
        assert "turns" in data
        assert "files" in data
        assert data["files"] == ["src/foo.py"]

    def test_returns_partial_when_db_missing(self, client, tmp_path):
        missing = str(tmp_path / "nonexistent.db")
        with patch("src.dashboard_api.DB_PATH", missing):
            resp = client.get("/api/session/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checkpoints"] == []
        assert data["turns"] == []
        assert data["files"] == []


class TestApiFiles:
    def test_returns_file_list(self, client, populated_db):
        _conn, db_path = populated_db
        with patch("src.dashboard_api.DB_PATH", db_path):
            resp = client.get("/api/files")
        assert resp.status_code == 200
        data = resp.json()
        assert any(f["file_path"] == "src/foo.py" for f in data)

    def test_returns_empty_when_db_missing(self, client, tmp_path):
        missing = str(tmp_path / "nonexistent.db")
        with patch("src.dashboard_api.DB_PATH", missing):
            resp = client.get("/api/files")
        assert resp.status_code == 200
        assert resp.json() == []


class TestApiProcesses:
    def test_returns_dict(self, client):
        from dataclasses import asdict

        fake = {"sess-1": ProcessInfo(pid=999, state="working")}
        with (
            patch("src.dashboard_api.get_running_sessions", return_value=fake),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/processes")
        assert resp.status_code == 200
        data = resp.json()["sess-1"]
        assert data["pid"] == 999
        assert data["state"] == "working"
        assert "terminal_hwnd" not in data  # internal field, not in API schema


class TestApiFocus:
    def test_success(self, client):
        with patch("src.dashboard_api.focus_session_window", return_value=(True, "Focused: Terminal")):
            resp = client.post("/api/focus/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Focused" in data["message"]

    def test_failure(self, client):
        with patch("src.dashboard_api.focus_session_window", return_value=(False, "Not found")):
            resp = client.post("/api/focus/sess-1")
        data = resp.json()
        assert data["success"] is False


class TestApiDismiss:
    def test_dismiss_adds_hidden_session_to_config(self, client):
        cfg: dict = {}
        with (
            patch("src.dashboard_api._read_dashboard_config", return_value=cfg),
            patch("src.dashboard_api._write_dashboard_config") as mock_write,
        ):
            resp = client.post("/api/dismiss/sess-123")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        written_cfg = mock_write.call_args[0][0]
        assert written_cfg["hidden_sessions"] == ["sess-123"]

    def test_dismiss_rejects_invalid_session_id(self, client):
        resp = client.post("/api/dismiss/not valid")
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_dismiss_same_session_twice_no_duplicates(self, client):
        first_cfg: dict = {}
        second_cfg: dict = {"hidden_sessions": ["sess-dup"]}
        with (
            patch("src.dashboard_api._read_dashboard_config", side_effect=[first_cfg, second_cfg]),
            patch("src.dashboard_api._write_dashboard_config") as mock_write,
        ):
            first = client.post("/api/dismiss/sess-dup")
            second = client.post("/api/dismiss/sess-dup")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["message"] == "Session already dismissed."
        assert first_cfg["hidden_sessions"] == ["sess-dup"]
        assert second_cfg["hidden_sessions"] == ["sess-dup"]
        assert mock_write.call_count == 1


class TestApiKill:
    def test_session_not_found(self, client):
        with (
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.post("/api/kill/sess-1")
        assert resp.status_code == 404
        assert resp.json()["success"] is False

    def test_no_pid_available(self, client):
        running = {"sess-1": ProcessInfo(pid=0, state="working", cmdline="copilot --resume sess-1")}
        with (
            patch("src.dashboard_api.get_running_sessions", return_value=running),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.post("/api/kill/sess-1")
        assert resp.status_code == 404
        assert resp.json()["success"] is False

    def test_success_unix(self, client):
        running = {"sess-1": ProcessInfo(pid=1234, state="working", cmdline="copilot --resume sess-1")}
        with (
            patch("src.dashboard_api.get_running_sessions", return_value=running),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
            patch("src.dashboard_api.sys.platform", "linux"),
            patch("src.dashboard_api.os.kill") as mock_kill,
        ):
            resp = client.post("/api/kill/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "1234" in data["message"]
        mock_kill.assert_called_once_with(1234, signal.SIGTERM)

    def test_success_windows(self, client):
        running = {"sess-1": ProcessInfo(pid=5678, state="working", cmdline="copilot --resume sess-1")}
        with (
            patch("src.dashboard_api.get_running_sessions", return_value=running),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
            patch("src.dashboard_api.sys.platform", "win32"),
            patch("src.dashboard_api.subprocess.run") as mock_run,
        ):
            resp = client.post("/api/kill/sess-1")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "taskkill" in args
        assert str(5678) in args

    def test_kill_failure(self, client):
        running = {"sess-1": ProcessInfo(pid=1234, state="working", cmdline="copilot --resume sess-1")}
        with (
            patch("src.dashboard_api.get_running_sessions", return_value=running),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
            patch("src.dashboard_api.sys.platform", "linux"),
            patch("src.dashboard_api.os.kill", side_effect=OSError("no such process")),
        ):
            resp = client.post("/api/kill/sess-1")
        assert resp.status_code == 500
        assert resp.json()["success"] is False


class TestApiServerInfo:
    def test_returns_pid_and_port(self, client):
        resp = client.get("/api/server-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "pid" in data
        assert "port" in data


class TestManifest:
    def test_returns_pwa_manifest(self, client):
        resp = client.get("/manifest.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Copilot Dashboard"
        assert "icons" in data
        assert data["display"] == "standalone"


class TestServiceWorker:
    def test_returns_js(self, client):
        resp = client.get("/sw.js")
        assert resp.status_code == 200
        assert "application/javascript" in resp.headers["content-type"]
        assert b"fetch" in resp.content


# ── Events fallback (no DB) ─────────────────────────────────────────────────


class TestSessionsFromEvents:
    """Test _sessions_from_events() — builds Copilot sessions from events.jsonl."""

    @pytest.fixture
    def events_dir(self, tmp_path):
        """Create a mock session-state directory with events.jsonl files."""
        session_dir = tmp_path / "session-state" / "test-sess-001"
        session_dir.mkdir(parents=True)
        events = [
            json.dumps({
                "type": "session.start",
                "data": {"sessionId": "test-sess-001", "startTime": "2026-03-01T10:00:00Z"},
                "timestamp": "2026-03-01T10:00:00Z",
            }),
            json.dumps({
                "type": "session.resume",
                "data": {"context": {"cwd": "/home/user/project", "branch": "main", "repository": "org/repo"}},
                "timestamp": "2026-03-01T10:00:01Z",
            }),
            json.dumps({
                "type": "user.message",
                "data": {"content": "Fix the authentication bug"},
                "timestamp": "2026-03-01T10:00:05Z",
            }),
            json.dumps({
                "type": "assistant.turn_end",
                "data": {"turnId": "0"},
                "timestamp": "2026-03-01T10:05:00Z",
            }),
            json.dumps({
                "type": "user.message",
                "data": {"content": "Now add tests"},
                "timestamp": "2026-03-01T10:06:00Z",
            }),
            json.dumps({
                "type": "assistant.turn_end",
                "data": {"turnId": "1"},
                "timestamp": "2026-03-01T10:10:00Z",
            }),
        ]
        (session_dir / "events.jsonl").write_text("\n".join(events), encoding="utf-8")
        return str(tmp_path / "session-state")

    def test_returns_sessions_from_events(self, client, events_dir, tmp_path):
        missing_db = str(tmp_path / "nonexistent.db")
        with (
            patch("src.dashboard_api.DB_PATH", missing_db),
            patch("src.dashboard_api.SESSION_STATE_DIR", events_dir),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert s["id"] == "test-sess-001"
        assert s["cwd"] == "/home/user/project"
        assert s["branch"] == "main"
        assert s["summary"] == "Fix the authentication bug"
        assert s["turn_count"] == 2
        assert s["source"] == "copilot"

    def test_empty_when_no_session_state_dir(self, client, tmp_path):
        missing_db = str(tmp_path / "nonexistent.db")
        with (
            patch("src.dashboard_api.DB_PATH", missing_db),
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path / "no-such-dir")),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_skips_dirs_without_events(self, client, events_dir, tmp_path):
        # Add a session dir with no events.jsonl
        empty_dir = os.path.join(events_dir, "empty-sess")
        os.makedirs(empty_dir)
        missing_db = str(tmp_path / "nonexistent.db")
        with (
            patch("src.dashboard_api.DB_PATH", missing_db),
            patch("src.dashboard_api.SESSION_STATE_DIR", events_dir),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        assert resp.status_code == 200
        # Only the session with events.jsonl should appear
        assert len(resp.json()) == 1

    def test_running_session_enriched_from_events(self, client, events_dir, tmp_path):
        missing_db = str(tmp_path / "nonexistent.db")
        proc = ProcessInfo(pid=1234, state="working")
        with (
            patch("src.dashboard_api.DB_PATH", missing_db),
            patch("src.dashboard_api.SESSION_STATE_DIR", events_dir),
            patch("src.dashboard_api.get_running_sessions", return_value={"test-sess-001": proc}),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData()),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["is_running"] is True
        assert data[0]["state"] == "working"

    def test_detail_fallback_when_db_missing(self, client, tmp_path):
        """Session detail returns partial data from events when DB is missing."""
        missing_db = str(tmp_path / "nonexistent.db")
        session_dir = tmp_path / "session-state" / "test-sess-002"
        session_dir.mkdir(parents=True)
        events = [
            json.dumps({
                "type": "tool.execution_start",
                "data": {"toolName": "powershell"},
                "timestamp": "2026-03-01T10:00:00Z",
            }),
            json.dumps({
                "type": "tool.execution_start",
                "data": {"toolName": "powershell"},
                "timestamp": "2026-03-01T10:00:01Z",
            }),
            json.dumps({
                "type": "tool.execution_start",
                "data": {"toolName": "view"},
                "timestamp": "2026-03-01T10:00:02Z",
            }),
        ]
        (session_dir / "events.jsonl").write_text("\n".join(events), encoding="utf-8")
        with (
            patch("src.dashboard_api.DB_PATH", missing_db),
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path / "session-state")),
        ):
            resp = client.get("/api/session/test-sess-002")
        assert resp.status_code == 200
        data = resp.json()
        assert data["checkpoints"] == []
        assert data["turns"] == []
        tool_names = {t["name"] for t in data["tool_counts"]}
        assert "powershell" in tool_names
