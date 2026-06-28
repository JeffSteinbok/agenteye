"""Tests for /api/version and /api/update endpoints."""

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import src.dashboard_api as dashboard_api
from src.dashboard_api import _version_cache


@pytest.fixture(autouse=True)
def reset_version_cache():
    """Reset the version cache before each test."""
    _version_cache.latest = None
    _version_cache.update_available = False
    _version_cache.checked_at = 0.0
    yield
    _version_cache.latest = None
    _version_cache.update_available = False
    _version_cache.checked_at = 0.0


def _make_pypi_response(version: str, releases: dict | None = None) -> MagicMock:
    """Build a fake urllib response returning the given version."""
    data: dict = {"info": {"version": version}}
    if releases is not None:
        data["releases"] = releases
    else:
        # Default: include the version in releases so pre-release logic works
        data["releases"] = {version: []}
    body = json.dumps(data).encode()
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ---------------------------------------------------------------------------
# /api/version
# ---------------------------------------------------------------------------


class TestApiVersion:
    def test_returns_current_version(self, client):
        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response("99.0.0")):
            resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == dashboard_api.__version__
        assert data["latest"] == "99.0.0"
        assert data["update_available"] is True

    def test_no_update_when_same_version(self, client):
        current = dashboard_api.__version__
        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response(current)):
            resp = client.get("/api/version")
        data = resp.json()
        assert data["update_available"] is False
        assert data["latest"] == current

    def test_uses_cache_on_second_call(self, client):
        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response("5.0.0")) as mock_urlopen:
            client.get("/api/version")
            client.get("/api/version")
        # PyPI should only be hit once; second call served from cache
        assert mock_urlopen.call_count == 1

    def test_cache_expires_after_ttl(self, client):
        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response("5.0.0")):
            client.get("/api/version")

        # Force the cache to appear expired by backdating checked_at beyond the TTL
        _version_cache.checked_at = time.monotonic() - dashboard_api.VERSION_CACHE_TTL - 1

        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response("6.0.0")) as mock2:
            resp = client.get("/api/version")
        assert mock2.call_count == 1
        assert resp.json()["latest"] == "6.0.0"

    def test_pypi_failure_returns_current(self, client):
        with patch("src.dashboard_api.urllib.request.urlopen", side_effect=Exception("network error")):
            resp = client.get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == dashboard_api.__version__
        assert data["update_available"] is False

    def test_pypi_timeout_returns_current(self, client):
        import urllib.error

        with patch("src.dashboard_api.urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            resp = client.get("/api/version")
        data = resp.json()
        assert data["update_available"] is False

    def test_response_shape(self, client):
        with patch("src.dashboard_api.urllib.request.urlopen", return_value=_make_pypi_response("1.2.3")):
            resp = client.get("/api/version")
        data = resp.json()
        assert "current" in data
        assert "latest" in data
        assert "update_available" in data


# ---------------------------------------------------------------------------
# /api/update
# ---------------------------------------------------------------------------


class TestApiUpdate:
    def test_returns_success(self, client):
        with patch("src.dashboard_api.subprocess.Popen") as mock_popen:
            resp = client.post("/api/update")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "restart" in data["message"].lower()

    def test_spawns_subprocess(self, client):
        with patch("src.dashboard_api.subprocess.Popen") as mock_popen:
            client.post("/api/update")
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        assert cmd[0] == dashboard_api.sys.executable
        assert cmd[1] == "-c"
        # The inline script should reference pip and the package name
        script = cmd[2]
        assert "pip" in script
        assert "agenteye" in script

    def test_script_contains_server_pid(self, client):
        with patch("src.dashboard_api.subprocess.Popen") as mock_popen:
            with patch("src.dashboard_api.os.getpid", return_value=99999):
                client.post("/api/update")
        script = mock_popen.call_args[0][0][2]
        assert "99999" in script

    def test_script_contains_port(self, client):
        with patch("src.dashboard_api.subprocess.Popen") as mock_popen:
            client.post("/api/update")
        script = mock_popen.call_args[0][0][2]
        assert "start" in script
        assert "--port" in script

    def test_windows_uses_detached_flags(self, client):
        with (
            patch("src.dashboard_api.subprocess.Popen") as mock_popen,
            patch("src.dashboard_api.sys.platform", "win32"),
        ):
            client.post("/api/update")
        _args, kwargs = mock_popen.call_args
        assert "creationflags" in kwargs
        # CREATE_NO_WINDOW (0x8000000) | DETACHED_PROCESS (0x8)
        assert kwargs["creationflags"] & 0x00000008  # DETACHED_PROCESS bit set

    def test_unix_uses_start_new_session(self, client):
        with (
            patch("src.dashboard_api.subprocess.Popen") as mock_popen,
            patch("src.dashboard_api.sys.platform", "linux"),
        ):
            client.post("/api/update")
        _args, kwargs = mock_popen.call_args
        assert kwargs.get("start_new_session") is True
        assert "creationflags" not in kwargs
