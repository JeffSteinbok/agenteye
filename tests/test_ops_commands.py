"""Tests for CLI commands: server detection, autostart, and upgrade."""

import argparse
import json
import sys
from unittest.mock import MagicMock, patch

import pytest

from src.session_dashboard import (
    TASK_NAME,
    _get_autostart_cmd_str,
    _kill_pid,
    _probe_server,
    cmd_autostart,
    cmd_autostart_remove,
    cmd_start,
    cmd_status,
    cmd_stop,
    cmd_upgrade,
)

# ---------------------------------------------------------------------------
# _probe_server
# ---------------------------------------------------------------------------


class TestProbeServer:
    @patch("src.session_dashboard.urllib.request.urlopen")
    def test_returns_dict_on_success(self, mock_urlopen):
        payload = {"pid": 1234, "port": "5111", "sync_folder": None}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _probe_server(5111)
        assert result == payload

    @patch("src.session_dashboard.urllib.request.urlopen", side_effect=ConnectionRefusedError)
    def test_returns_none_on_connection_refused(self, _mock):
        assert _probe_server(5111) is None

    @patch("src.session_dashboard.urllib.request.urlopen", side_effect=TimeoutError)
    def test_returns_none_on_timeout(self, _mock):
        assert _probe_server(5111) is None

    @patch("src.session_dashboard.urllib.request.urlopen")
    def test_returns_none_on_bad_json(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        assert _probe_server(5111) is None


# ---------------------------------------------------------------------------
# _kill_pid
# ---------------------------------------------------------------------------


class TestKillPid:
    @patch("src.session_dashboard.sys")
    @patch("src.session_dashboard.subprocess.run")
    def test_uses_taskkill_on_windows(self, mock_run, mock_sys):
        mock_sys.platform = "win32"
        _kill_pid(1234)
        mock_run.assert_called_once_with(
            ["taskkill", "/F", "/PID", "1234"], capture_output=True, check=False
        )

    @patch("src.session_dashboard.sys")
    @patch("src.session_dashboard.os.kill")
    def test_uses_sigterm_on_unix(self, mock_kill, mock_sys):
        mock_sys.platform = "linux"
        import signal

        _kill_pid(1234)
        mock_kill.assert_called_once_with(1234, signal.SIGTERM)


# ---------------------------------------------------------------------------
# cmd_start — already running detection
# ---------------------------------------------------------------------------


class TestCmdStart:
    @patch("src.session_dashboard._probe_server", return_value={"pid": 999, "port": "5111"})
    def test_skips_if_already_running(self, _probe, capsys):
        args = argparse.Namespace(port=5111, background=False)
        cmd_start(args)
        out = capsys.readouterr().out
        assert "already running" in out.lower()
        assert "999" in out


# ---------------------------------------------------------------------------
# cmd_stop
# ---------------------------------------------------------------------------


class TestCmdStop:
    @patch("src.session_dashboard._probe_server", return_value=None)
    def test_prints_not_running(self, _probe, capsys):
        cmd_stop(argparse.Namespace(port=5111))
        out = capsys.readouterr().out
        assert "not running" in out.lower()

    @patch("src.session_dashboard._kill_pid")
    @patch(
        "src.session_dashboard._probe_server",
        return_value={"pid": 1234, "port": "5111"},
    )
    def test_kills_server(self, _probe, mock_kill, capsys):
        cmd_stop(argparse.Namespace(port=5111))
        mock_kill.assert_called_once_with(1234)
        out = capsys.readouterr().out
        assert "stopped" in out.lower()
        assert "1234" in out

    @patch(
        "src.session_dashboard._probe_server",
        return_value={"port": "5111"},
    )
    def test_handles_missing_pid(self, _probe, capsys):
        cmd_stop(argparse.Namespace(port=5111))
        out = capsys.readouterr().out
        assert "did not report a PID" in out


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------


class TestCmdStatus:
    @patch("src.session_dashboard._probe_server", return_value=None)
    def test_not_running(self, _probe, capsys):
        cmd_status(argparse.Namespace(port=5111))
        out = capsys.readouterr().out
        assert "not running" in out.lower()

    @patch(
        "src.session_dashboard._probe_server",
        return_value={"pid": 4567, "port": "5111"},
    )
    def test_running(self, _probe, capsys):
        cmd_status(argparse.Namespace(port=5111))
        out = capsys.readouterr().out
        assert "4567" in out
        assert "running" in out.lower()


# ---------------------------------------------------------------------------
# _get_autostart_cmd_str
# ---------------------------------------------------------------------------


class TestGetAutostartCmdStr:
    def test_uses_copilot_dashboard_when_found(self):
        with patch("shutil.which", return_value="C:\\copilot-dashboard.exe"):
            result = _get_autostart_cmd_str(5111)
        assert result == '"C:\\copilot-dashboard.exe" start --background --port 5111'

    def test_falls_back_to_python_module(self):
        with patch("shutil.which", return_value=None):
            result = _get_autostart_cmd_str(8080)
        assert sys.executable in result
        assert "8080" in result
        assert "-m src.session_dashboard" in result

    def test_app_mode_uses_hidden_flag(self):
        with patch("shutil.which", return_value="C:\\copilot-dashboard.exe"):
            result = _get_autostart_cmd_str(5111, mode="app")
        assert result == '"C:\\copilot-dashboard.exe" app --hidden --port 5111'

    def test_app_mode_fallback_to_python_module(self):
        with patch("shutil.which", return_value=None):
            result = _get_autostart_cmd_str(8080, mode="app")
        assert sys.executable in result
        assert "app --hidden" in result
        assert "--port 8080" in result


# ---------------------------------------------------------------------------
# cmd_autostart — platform gate + registry
# ---------------------------------------------------------------------------


class TestCmdAutostart:
    def test_errors_on_unsupported_platform(self):
        args = argparse.Namespace(port=5111, mode="server")
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            with pytest.raises(SystemExit):
                cmd_autostart(args)

    @patch("src.session_dashboard._macos_autostart_enable")
    def test_enables_launch_agent_on_macos(self, mock_enable):
        args = argparse.Namespace(port=5111, mode="app")
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "darwin"
            cmd_autostart(args)
        mock_enable.assert_called_once_with(5111, "app")

    @patch("src.session_dashboard.sys")
    @patch("shutil.which", return_value="C:\\copilot-dashboard.exe")
    def test_writes_registry_on_windows(self, _which, mock_sys):
        mock_sys.platform = "win32"
        mock_sys.exit = sys.exit
        mock_sys.executable = sys.executable
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        args = argparse.Namespace(port=5111, mode="server")
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            cmd_autostart(args)
        mock_winreg.SetValueEx.assert_called_once()
        set_call = mock_winreg.SetValueEx.call_args
        assert set_call[0][0] == mock_key
        assert set_call[0][1] == TASK_NAME

    @patch("src.session_dashboard.sys")
    @patch("shutil.which", return_value="C:\\copilot-dashboard.exe")
    def test_fails_gracefully(self, _which, mock_sys):
        mock_sys.platform = "win32"
        mock_sys.exit = MagicMock(side_effect=SystemExit(1))
        mock_sys.executable = sys.executable
        mock_winreg = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock()
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        mock_winreg.SetValueEx.side_effect = OSError("Permission denied")
        args = argparse.Namespace(port=5111, mode="server")
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            with pytest.raises(SystemExit):
                cmd_autostart(args)


# ---------------------------------------------------------------------------
# cmd_autostart_remove — platform gate + registry
# ---------------------------------------------------------------------------


class TestCmdAutostartRemove:
    def test_errors_on_unsupported_platform(self):
        args = argparse.Namespace()
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            with pytest.raises(SystemExit):
                cmd_autostart_remove(args)

    @patch("src.session_dashboard._macos_autostart_remove")
    def test_removes_launch_agent_on_macos(self, mock_remove):
        args = argparse.Namespace()
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "darwin"
            cmd_autostart_remove(args)
        mock_remove.assert_called_once()

    @patch("src.session_dashboard.sys")
    def test_deletes_registry_value_on_windows(self, mock_sys):
        mock_sys.platform = "win32"
        mock_sys.exit = sys.exit
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            cmd_autostart_remove(argparse.Namespace())
        mock_winreg.DeleteValue.assert_called_once_with(mock_key, TASK_NAME)

    @patch("src.session_dashboard.sys")
    def test_handles_not_found(self, mock_sys, capsys):
        mock_sys.platform = "win32"
        mock_sys.exit = sys.exit
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.DeleteValue.side_effect = FileNotFoundError
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            cmd_autostart_remove(argparse.Namespace())
        out = capsys.readouterr().out
        assert "not currently configured" in out


# ---------------------------------------------------------------------------
# cmd_upgrade — refresh message
# ---------------------------------------------------------------------------


class TestUpgradeRefreshMessage:
    @patch("src.session_dashboard.subprocess.Popen")
    @patch("shutil.which", return_value="copilot-dashboard")
    @patch("src.session_dashboard.subprocess.run")
    @patch("src.session_dashboard._probe_server", return_value={"pid": 12345, "port": "5111"})
    @patch("src.session_dashboard._kill_pid")
    def test_prints_refresh_message(self, _kill, _probe, mock_run, _which, _popen, capsys):
        # pip upgrade succeeds
        mock_run.side_effect = [
            MagicMock(returncode=0),  # pip install
            MagicMock(returncode=0, stdout="0.8.0\n"),  # version check
        ]
        cmd_upgrade(argparse.Namespace(port=5111))
        out = capsys.readouterr().out
        assert "refresh your browser" in out.lower()


# ---------------------------------------------------------------------------
# API: /api/autostart endpoints
# ---------------------------------------------------------------------------


class TestApiAutostartStatus:
    @patch("src.dashboard_api.sys")
    def test_supported_and_enabled(self, mock_sys, client):
        mock_sys.platform = "win32"
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_READ = 0x20019
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            resp = client.get("/api/autostart")
        assert resp.status_code == 200
        data = resp.json()
        assert data["supported"] is True
        assert data["enabled"] is True

    @patch("src.dashboard_api.sys")
    def test_supported_but_not_enabled(self, mock_sys, client):
        mock_sys.platform = "win32"
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_READ = 0x20019
        mock_winreg.QueryValueEx.side_effect = FileNotFoundError
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            resp = client.get("/api/autostart")
        data = resp.json()
        assert data["supported"] is True
        assert data["enabled"] is False

    @patch("src.dashboard_api.sys")
    def test_not_supported_on_mac(self, mock_sys, client):
        mock_sys.platform = "darwin"
        resp = client.get("/api/autostart")
        data = resp.json()
        assert data["supported"] is False
        assert data["enabled"] is False


class TestApiAutostartEnable:
    @patch("src.dashboard_api.sys")
    def test_fails_on_non_windows(self, mock_sys, client):
        mock_sys.platform = "linux"
        resp = client.post("/api/autostart/enable")
        data = resp.json()
        assert data["success"] is False

    @patch("src.dashboard_api.sys")
    def test_success_on_windows(self, mock_sys, client):
        mock_sys.platform = "win32"
        mock_sys.executable = sys.executable
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            with patch("shutil.which", return_value="C:\\copilot-dashboard.exe"):
                resp = client.post("/api/autostart/enable")
        data = resp.json()
        assert data["success"] is True

    @patch("src.dashboard_api.sys")
    def test_failure_on_windows(self, mock_sys, client):
        mock_sys.platform = "win32"
        mock_sys.executable = sys.executable
        mock_winreg = MagicMock()
        mock_key = MagicMock()
        mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
        mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
        mock_winreg.HKEY_CURRENT_USER = 0x80000001
        mock_winreg.KEY_SET_VALUE = 0x0002
        mock_winreg.REG_SZ = 1
        mock_winreg.SetValueEx.side_effect = OSError("Access denied")
        with patch.dict("sys.modules", {"winreg": mock_winreg}):
            with patch("shutil.which", return_value="C:\\copilot-dashboard.exe"):
                resp = client.post("/api/autostart/enable")
        data = resp.json()
        assert data["success"] is False
        assert "Access denied" in data["message"]
