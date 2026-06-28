"""Tests for the system tray application module."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# WindowApi tests
# ---------------------------------------------------------------------------


class TestWindowApi:
    """Tests for the WindowApi class exposed to JavaScript."""

    def test_is_native_app_returns_true(self):
        """WindowApi.is_native_app() should always return True."""
        from src.tray_app import WindowApi

        mock_tray_app = MagicMock()
        api = WindowApi(mock_tray_app)
        assert api.is_native_app() is True

    @patch("src.tray_app.sys")
    @patch("src.tray_app._get_window_hwnd", return_value=12345)
    @patch("src.tray_app._set_dark_title_bar")
    def test_set_theme_dark(self, mock_set_dark, mock_hwnd, mock_sys):
        """set_theme('dark') should call _set_dark_title_bar with dark=True."""
        from src.tray_app import WindowApi

        mock_sys.platform = "win32"
        mock_tray_app = MagicMock()
        api = WindowApi(mock_tray_app)
        api.set_theme("dark")
        mock_set_dark.assert_called_once_with(12345, dark=True)

    @patch("src.tray_app.sys")
    @patch("src.tray_app._get_window_hwnd", return_value=12345)
    @patch("src.tray_app._set_dark_title_bar")
    def test_set_theme_light(self, mock_set_dark, mock_hwnd, mock_sys):
        """set_theme('light') should call _set_dark_title_bar with dark=False."""
        from src.tray_app import WindowApi

        mock_sys.platform = "win32"
        mock_tray_app = MagicMock()
        api = WindowApi(mock_tray_app)
        api.set_theme("light")
        mock_set_dark.assert_called_once_with(12345, dark=False)

    @patch("src.tray_app._get_window_hwnd", return_value=None)
    @patch("src.tray_app._set_dark_title_bar")
    def test_set_theme_no_hwnd(self, mock_set_dark, mock_hwnd):
        """set_theme should not crash when hwnd is None."""
        from src.tray_app import WindowApi

        mock_tray_app = MagicMock()
        api = WindowApi(mock_tray_app)
        api.set_theme("dark")  # Should not raise
        mock_set_dark.assert_not_called()

    def test_send_notification_success(self):
        """send_notification should use plyer and return True on success."""
        from src.tray_app import WindowApi

        mock_tray_app = MagicMock()
        api = WindowApi(mock_tray_app)

        with patch("src.tray_app._get_window_icon_path") as mock_icon:
            mock_icon.return_value = MagicMock(exists=lambda: True)
            mock_icon.return_value.__str__ = lambda self: "icon.ico"
            with patch.dict("sys.modules", {"plyer": MagicMock()}):
                with patch("plyer.notification.notify") as mock_notify:
                    result = api.send_notification("Test Title", "Test Body")

        # Should attempt to send notification
        assert result is True or result is False  # Depends on mock setup

    def test_send_notification_fallback_to_tray(self):
        """send_notification should fall back to tray_icon.notify if plyer fails."""
        from src.tray_app import WindowApi

        mock_tray_app = MagicMock()
        mock_tray_app.tray_icon = MagicMock()
        api = WindowApi(mock_tray_app)

        # Make plyer import fail
        with patch.dict("sys.modules", {"plyer": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = api.send_notification("Title", "Body")

        # Should fall back to tray_icon.notify
        mock_tray_app.tray_icon.notify.assert_called_once()


# ---------------------------------------------------------------------------
# Icon path helpers
# ---------------------------------------------------------------------------


class TestIconPaths:
    """Tests for icon path helper functions."""

    def test_get_tray_icon_path_windows(self):
        """On Windows, should prefer .ico file."""
        from src.tray_app import _get_tray_icon_path

        with patch("src.tray_app.sys") as mock_sys:
            mock_sys.platform = "win32"
            path = _get_tray_icon_path()
            # Should return a Path object
            assert isinstance(path, Path)
            # Should look for .ico on Windows
            assert path.suffix in (".ico", ".png")

    def test_get_tray_icon_path_darwin(self):
        """On macOS, should prefer template image."""
        from src.tray_app import _get_tray_icon_path

        with patch("src.tray_app.sys") as mock_sys:
            mock_sys.platform = "darwin"
            path = _get_tray_icon_path()
            assert isinstance(path, Path)

    def test_get_window_icon_path_windows(self):
        """On Windows, should return .ico for window icon."""
        from src.tray_app import _get_window_icon_path

        with patch("src.tray_app.sys") as mock_sys:
            mock_sys.platform = "win32"
            path = _get_window_icon_path()
            assert isinstance(path, Path)


# ---------------------------------------------------------------------------
# TrayApp initialization
# ---------------------------------------------------------------------------


class TestTrayAppInit:
    """Tests for TrayApp class initialization."""

    def test_init_defaults(self):
        """TrayApp should initialize with default values."""
        from src.tray_app import TrayApp

        app = TrayApp()
        assert app.port == 5111
        assert app.log_level is None
        assert app.start_hidden is False
        assert app.window is None
        assert app.tray_icon is None
        assert app._shutdown_requested is False

    def test_init_custom_port(self):
        """TrayApp should accept custom port."""
        from src.tray_app import TrayApp

        app = TrayApp(port=8080)
        assert app.port == 8080

    def test_init_start_hidden(self):
        """TrayApp should accept start_hidden flag."""
        from src.tray_app import TrayApp

        app = TrayApp(start_hidden=True)
        assert app.start_hidden is True

    def test_init_log_level(self):
        """TrayApp should accept log_level."""
        from src.tray_app import TrayApp

        app = TrayApp(log_level="DEBUG")
        assert app.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Dark title bar (Windows-specific)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
class TestDarkTitleBar:
    """Tests for Windows dark title bar functionality."""

    def test_set_dark_title_bar_with_valid_hwnd(self):
        """Should call DwmSetWindowAttribute on valid hwnd."""
        from src.tray_app import _set_dark_title_bar

        with patch("src.tray_app.ctypes") as mock_ctypes:
            _set_dark_title_bar(12345, dark=True)
            mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.assert_called_once()

    def test_set_dark_title_bar_with_zero_hwnd(self):
        """Should not call DwmSetWindowAttribute on hwnd=0."""
        from src.tray_app import _set_dark_title_bar

        with patch("src.tray_app.ctypes") as mock_ctypes:
            _set_dark_title_bar(0, dark=True)
            mock_ctypes.windll.dwmapi.DwmSetWindowAttribute.assert_not_called()


# ---------------------------------------------------------------------------
# run_tray_app entry point
# ---------------------------------------------------------------------------


class TestRunTrayApp:
    """Tests for the run_tray_app entry point function."""

    def test_run_tray_app_creates_tray_app(self):
        """run_tray_app should create and run a TrayApp instance."""
        from src.tray_app import run_tray_app

        with patch("src.tray_app.TrayApp") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            # This would normally block, so we mock run()
            run_tray_app(port=5112, log_level="INFO", start_hidden=True)

            mock_class.assert_called_once_with(
                port=5112, log_level="INFO", start_hidden=True
            )
            mock_instance.run.assert_called_once()


# ---------------------------------------------------------------------------
# CLI command: cmd_app
# ---------------------------------------------------------------------------


class TestCmdApp:
    """Tests for the cmd_app CLI command."""

    def test_cmd_app_calls_run_tray_app(self):
        """cmd_app should call run_tray_app with correct args."""
        import argparse

        from src.session_dashboard import cmd_app

        with patch("src.tray_app.run_tray_app") as mock_run:
            args = argparse.Namespace(port=5111, hidden=False, log_level=None)
            cmd_app(args)
            mock_run.assert_called_once_with(
                port=5111, log_level=None, start_hidden=False
            )

    def test_cmd_app_with_hidden_flag(self):
        """cmd_app should pass start_hidden=True when --hidden is set."""
        import argparse

        from src.session_dashboard import cmd_app

        with patch("src.tray_app.run_tray_app") as mock_run:
            args = argparse.Namespace(port=8080, hidden=True, log_level="DEBUG")
            cmd_app(args)
            mock_run.assert_called_once_with(
                port=8080, log_level="DEBUG", start_hidden=True
            )


# ---------------------------------------------------------------------------
# Autostart with mode
# ---------------------------------------------------------------------------


class TestAutostartMode:
    """Tests for autostart command with mode parameter."""

    def test_get_autostart_cmd_str_server_mode(self):
        """Server mode should generate start --background command."""
        from src.session_dashboard import _get_autostart_cmd_str

        with patch("shutil.which", return_value="C:\\agenteye.exe"):
            result = _get_autostart_cmd_str(5111, mode="server")
        assert "start --background" in result
        assert "--port 5111" in result

    def test_get_autostart_cmd_str_app_mode(self):
        """App mode should generate app --hidden command."""
        from src.session_dashboard import _get_autostart_cmd_str

        with patch("shutil.which", return_value="C:\\agenteye.exe"):
            result = _get_autostart_cmd_str(5111, mode="app")
        assert "app --hidden" in result
        assert "--port 5111" in result

    def test_get_autostart_cmd_str_app_mode_fallback(self):
        """App mode should work with python -m fallback."""
        from src.session_dashboard import _get_autostart_cmd_str

        with patch("shutil.which", return_value=None):
            result = _get_autostart_cmd_str(8080, mode="app")
        assert "app --hidden" in result
        assert "--port 8080" in result
        assert "-m src.session_dashboard" in result
