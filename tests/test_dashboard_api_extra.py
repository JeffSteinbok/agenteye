"""Extra tests for dashboard_api.py — coverage gaps."""

import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from src.dashboard_api import _extract_extra_args, app
from src.models import EventData, ProcessInfo


# ---------------------------------------------------------------------------
# _extract_extra_args — shlex parsing with fallback (lines 133-160)
# ---------------------------------------------------------------------------


class TestExtractExtraArgs:
    def test_parses_mcp_server_arg(self):
        cmdline = "copilot --resume abc --additional-mcp-config /tmp/mcp.json"
        result = _extract_extra_args(cmdline)
        assert "--additional-mcp-config" in result
        assert "/tmp/mcp.json" in result
        # --resume and its value should be stripped
        assert "--resume" not in result
        assert "abc" not in result

    def test_malformed_shlex_falls_back_to_split(self):
        # Unbalanced quote triggers ValueError in shlex.split
        cmdline = 'copilot --resume sess "unclosed'
        result = _extract_extra_args(cmdline)
        # Should still work via fallback to str.split()
        assert isinstance(result, str)

    def test_empty_cmdline(self):
        assert _extract_extra_args("") == ""

    def test_no_extra_args(self):
        result = _extract_extra_args("copilot --resume abc-123")
        assert result == ""

    def test_yolo_flag_preserved(self):
        result = _extract_extra_args("copilot --resume abc --yolo")
        assert "--yolo" in result


# ---------------------------------------------------------------------------
# Backfill cwd/branch/repo from events (lines 213-219)
# ---------------------------------------------------------------------------


class TestBackfillFromEvents:
    def test_session_with_null_cwd_gets_backfilled(self, client, mock_db):
        conn, db_path = mock_db
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("sess-bf", None, None, None, "Test", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.commit()

        evt = EventData(cwd="/from/events", branch="feat-branch", repository="org/repo")
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=evt),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        data = resp.json()
        session = data[0]
        assert session["cwd"] == "/from/events"
        assert session["branch"] == "feat-branch"
        assert session["repository"] == "org/repo"

    def test_existing_cwd_not_overwritten(self, client, mock_db):
        conn, db_path = mock_db
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("sess-keep", "/original", "orig/repo", "main", "Test", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.commit()

        evt = EventData(cwd="/from/events", branch="feat", repository="other/repo")
        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_running_sessions", return_value={}),
            patch("src.dashboard_api.get_session_event_data", return_value=evt),
            patch("src.dashboard_api.get_claude_sessions", return_value=[]),
            patch("src.dashboard_api.get_running_claude_sessions", return_value={}),
        ):
            resp = client.get("/api/sessions")
        data = resp.json()
        session = data[0]
        assert session["cwd"] == "/original"
        assert session["repository"] == "orig/repo"


# ---------------------------------------------------------------------------
# Tool counter from events.jsonl (lines 292-305)
# ---------------------------------------------------------------------------


class TestToolCounter:
    def test_counts_tool_calls_from_events(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("sess-tc", "/project", "owner/repo", "main", "Test", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.commit()

        # Write events.jsonl with tool calls
        session_dir = tmp_path / "sess-tc"
        session_dir.mkdir()
        events = [
            {"type": "tool.execution_start", "data": {"toolName": "grep"}},
            {"type": "tool.execution_start", "data": {"toolName": "grep"}},
            {"type": "tool.execution_start", "data": {"toolName": "edit"}},
        ]
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path)),
            patch("src.dashboard_api.get_recent_output", return_value=[]),
        ):
            resp = client.get(f"/api/session/sess-tc")
        data = resp.json()
        tool_counts = {tc["name"]: tc["count"] for tc in data["tool_counts"]}
        assert tool_counts["grep"] == 2
        assert tool_counts["edit"] == 1

    def test_missing_events_file(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("sess-noev", "/project", "owner/repo", "main", "Test", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.commit()

        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path)),
            patch("src.dashboard_api.get_recent_output", return_value=[]),
        ):
            resp = client.get(f"/api/session/sess-noev")
        data = resp.json()
        assert data["tool_counts"] == []


# ---------------------------------------------------------------------------
# Session plan endpoint
# ---------------------------------------------------------------------------


class TestSessionPlan:
    def test_reads_copilot_plan_file(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        plan_path = project_dir / "PLAN.md"
        plan_path.write_text("# Plan\n\n- [x] Done\n- [ ] Next\n", encoding="utf-8")
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            (
                "sess-plan",
                str(project_dir),
                "owner/repo",
                "main",
                "Test",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.commit()

        with patch("src.dashboard_api.DB_PATH", db_path):
            resp = client.get("/api/session/sess-plan/plan")

        data = resp.json()
        assert resp.status_code == 200
        assert data["path"] == str(plan_path)
        assert data["content"] == "# Plan\n\n- [x] Done\n- [ ] Next\n"
        assert data["progress"] == {"done": 1, "total": 2}
        assert data["mtime"]

    def test_uses_events_cwd_when_db_cwd_missing(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        project_dir = tmp_path / "events-project"
        project_dir.mkdir()
        (project_dir / "PLAN.md").write_text("From events", encoding="utf-8")
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            ("sess-events", None, None, None, "Test", "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.commit()

        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch("src.dashboard_api.get_session_event_data", return_value=EventData(cwd=str(project_dir))),
        ):
            resp = client.get("/api/session/sess-events/plan")

        assert resp.status_code == 200
        assert resp.json()["content"] == "From events"

    def test_uses_configured_plan_files_and_blocks_traversal(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        project_dir = tmp_path / "project"
        docs_dir = project_dir / "docs"
        project_dir.mkdir()
        docs_dir.mkdir()
        (tmp_path / "secret.md").write_text("secret", encoding="utf-8")
        expected = docs_dir / "PLAN.md"
        expected.write_text("docs plan", encoding="utf-8")
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            (
                "sess-config",
                str(project_dir),
                "owner/repo",
                "main",
                "Test",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.commit()

        with (
            patch("src.dashboard_api.DB_PATH", db_path),
            patch(
                "src.dashboard_api._read_dashboard_config",
                return_value={"planFiles": ["../secret.md", "docs/PLAN.md"]},
            ),
        ):
            resp = client.get("/api/session/sess-config/plan")

        data = resp.json()
        assert resp.status_code == 200
        assert data["path"] == str(expected)
        assert data["content"] == "docs plan"

    def test_reads_claude_plan_file(self, client, tmp_path):
        claude_projects = tmp_path / "claude-projects"
        actual_project = tempfile.mkdtemp(prefix="claudeplanrepo", dir=tempfile.gettempdir())
        project_dir = claude_projects / actual_project.strip("/").replace("/", "-")
        project_dir.mkdir(parents=True)
        (project_dir / "aaaa-1111.jsonl").write_text("{}", encoding="utf-8")
        plan_path = os.path.join(actual_project, "PLAN.md")
        with open(plan_path, "w", encoding="utf-8") as f:
            f.write("Claude plan")

        try:
            with patch("src.claude_code.CLAUDE_PROJECTS_DIR", str(claude_projects)):
                resp = client.get("/api/session/cc:aaaa-1111/plan")
        finally:
            shutil.rmtree(actual_project, ignore_errors=True)

        assert resp.status_code == 200
        assert resp.json()["content"] == "Claude plan"

    def test_returns_empty_when_no_plan_file_exists(self, client, mock_db, tmp_path):
        conn, db_path = mock_db
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        conn.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            (
                "sess-empty",
                str(project_dir),
                "owner/repo",
                "main",
                "Test",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.commit()

        with patch("src.dashboard_api.DB_PATH", db_path):
            resp = client.get("/api/session/sess-empty/plan")

        assert resp.status_code == 200
        assert resp.json() == {"path": None, "content": None, "mtime": None, "progress": None}


# ---------------------------------------------------------------------------
# favicon endpoint (lines 471-477)
# ---------------------------------------------------------------------------


class TestFavicon:
    def test_returns_404_when_missing(self, client, tmp_path):
        with patch("src.dashboard_api.STATIC_DIR", str(tmp_path)):
            resp = client.get("/favicon.png")
        assert resp.status_code == 404

    def test_returns_favicon_when_exists(self, client, tmp_path):
        # Create a fake favicon.png
        favicon = tmp_path / "favicon.png"
        favicon.write_bytes(b"\x89PNG\r\n\x1a\n")  # PNG magic bytes
        with patch("src.dashboard_api.STATIC_DIR", str(tmp_path)):
            resp = client.get("/favicon.png")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Index HTML fallback chain (lines 521-534)
# ---------------------------------------------------------------------------


class TestIndexFallback:
    def test_falls_back_to_legacy_template(self, client, tmp_path):
        dist_dir = str(tmp_path / "nonexistent_dist")
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "dashboard.html").write_text(
            "<html>{{ version }}</html>"
        )
        with (
            patch("src.dashboard_api.DIST_DIR", dist_dir),
            patch("src.dashboard_api.TEMPLATES_DIR", str(templates_dir)),
        ):
            resp = client.get("/")
        assert resp.status_code == 200
        # Version should be substituted
        from src.__version__ import __version__

        assert __version__ in resp.text

    def test_falls_back_to_bare_html(self, client, tmp_path):
        with (
            patch("src.dashboard_api.DIST_DIR", str(tmp_path / "no_dist")),
            patch("src.dashboard_api.TEMPLATES_DIR", str(tmp_path / "no_templates")),
        ):
            resp = client.get("/")
        assert resp.status_code == 200
        assert "Copilot Dashboard" in resp.text
        assert "No frontend build found" in resp.text

    def test_serves_dist_index_when_exists(self, client, tmp_path):
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        (dist_dir / "index.html").write_text("<html>React SPA</html>")
        with patch("src.dashboard_api.DIST_DIR", str(dist_dir)):
            resp = client.get("/")
        assert resp.status_code == 200
        assert "React SPA" in resp.text


# ---------------------------------------------------------------------------
# Auth middleware — verify token enforcement
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    """Verify that the auth middleware rejects unauthenticated /api/* requests."""

    def test_api_rejects_no_token(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app)
        resp = raw_client.get("/api/sessions")
        assert resp.status_code == 401
        assert resp.json() == {"error": "Unauthorized"}

    def test_api_rejects_wrong_token(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app)
        resp = raw_client.get("/api/sessions", params={"token": "bad-token"})
        assert resp.status_code == 401

    def test_api_accepts_bearer_header(self, client):
        from fastapi.testclient import TestClient

        from src.dashboard_api import API_TOKEN

        raw_client = TestClient(app)
        resp = raw_client.get(
            "/api/version",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_root_accessible_without_token(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app)
        resp = raw_client.get("/")
        assert resp.status_code == 200

    def test_token_injected_into_html(self):
        from fastapi.testclient import TestClient

        from src.dashboard_api import API_TOKEN

        raw_client = TestClient(app)
        resp = raw_client.get("/")
        assert API_TOKEN in resp.text
        assert "__DASHBOARD_TOKEN__" in resp.text
