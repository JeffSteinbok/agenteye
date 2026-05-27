"""Extra tests for dashboard_api.py — coverage gaps."""

import json
import os
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
            (
                "sess-keep",
                "/original",
                "orig/repo",
                "main",
                "Test",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
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
            (
                "sess-tc",
                "/project",
                "owner/repo",
                "main",
                "Test",
                "2026-01-01T00:00:00Z",
                "2026-01-02T00:00:00Z",
            ),
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
            (
                "sess-noev",
                "/project",
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
            patch("src.dashboard_api.SESSION_STATE_DIR", str(tmp_path)),
            patch("src.dashboard_api.get_recent_output", return_value=[]),
        ):
            resp = client.get(f"/api/session/sess-noev")
        data = resp.json()
        assert data["tool_counts"] == []


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
        (templates_dir / "dashboard.html").write_text("<html>{{ version }}</html>")
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
        assert "AI CLI Agent Dashboard" in resp.text
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

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/api/sessions")
        assert resp.status_code == 401
        assert resp.json() == {"error": "Unauthorized"}

    def test_api_rejects_wrong_token(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/api/sessions", params={"token": "bad-token"})
        assert resp.status_code == 401

    def test_api_accepts_bearer_header(self, client):
        from fastapi.testclient import TestClient

        from src.dashboard_api import API_TOKEN

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get(
            "/api/version",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_api_accepts_query_string_token_for_compat(self):
        """Backwards-compatibility: the ?token= query string still works.

        Production frontend uses Authorization: Bearer header, but the
        backend continues to honor the legacy query-string for compat
        with older bookmarks, in-page links, and scripted clients.
        """
        from fastapi.testclient import TestClient

        from src.dashboard_api import API_TOKEN

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/api/version", params={"token": API_TOKEN})
        assert resp.status_code == 200

    def test_root_accessible_without_token(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/")
        assert resp.status_code == 200

    def test_token_injected_into_html(self):
        from fastapi.testclient import TestClient

        from src.dashboard_api import API_TOKEN

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/")
        assert API_TOKEN in resp.text
        assert "__DASHBOARD_TOKEN__" in resp.text


class TestTrustedHostMiddleware:
    """Verify DNS-rebinding defense rejects unexpected Host headers."""

    def test_evil_host_rejected(self):
        """A request with `Host: evil.com` must be rejected with 400."""
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://evil.com")
        resp = raw_client.get("/")
        assert resp.status_code == 400
        # Starlette's default response text for TrustedHostMiddleware
        assert "Invalid host header" in resp.text

    def test_localhost_allowed(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/")
        assert resp.status_code == 200

    def test_loopback_ip_allowed(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://127.0.0.1")
        resp = raw_client.get("/")
        assert resp.status_code == 200


class TestDocsDisabled:
    """Verify Swagger UI and OpenAPI schema endpoints are disabled."""

    def test_docs_returns_404(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/docs")
        assert resp.status_code == 404

    def test_openapi_returns_404(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/openapi.json")
        assert resp.status_code == 404

    def test_redoc_returns_404(self):
        from fastapi.testclient import TestClient

        raw_client = TestClient(app, base_url="http://localhost")
        resp = raw_client.get("/redoc")
        assert resp.status_code == 404
