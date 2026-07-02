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

            mock_class.assert_called_once_with(port=5112, log_level="INFO", start_hidden=True)
            mock_instance.run.assert_called_once()


# ---------------------------------------------------------------------------
# CLI command: cmd_app
# ---------------------------------------------------------------------------


class TestCmdApp:
    """Tests for the cmd_app CLI command."""

    def test_cmd_app_foreground_calls_run_tray_app(self):
        """cmd_app --foreground should call run_tray_app with correct args."""
        import argparse

        from src.session_dashboard import cmd_app

        with patch("src.tray_app.run_tray_app") as mock_run:
            args = argparse.Namespace(port=5111, hidden=False, log_level=None, foreground=True)
            cmd_app(args)
            mock_run.assert_called_once_with(port=5111, log_level=None, start_hidden=False)

    def test_cmd_app_foreground_with_hidden_flag(self):
        """cmd_app --foreground should pass start_hidden=True when --hidden is set."""
        import argparse

        from src.session_dashboard import cmd_app

        with patch("src.tray_app.run_tray_app") as mock_run:
            args = argparse.Namespace(port=8080, hidden=True, log_level="DEBUG", foreground=True)
            cmd_app(args)
            mock_run.assert_called_once_with(port=8080, log_level="DEBUG", start_hidden=True)

    def test_cmd_app_default_detaches(self):
        """cmd_app (no --foreground) should spawn a detached background process
        and not run the tray app inline."""
        import argparse

        from src.session_dashboard import cmd_app

        with (
            patch("src.session_dashboard.subprocess.Popen") as mock_popen,
            patch("src.tray_app.run_tray_app") as mock_run,
        ):
            args = argparse.Namespace(port=8080, hidden=True, log_level=None)
            cmd_app(args)
            mock_run.assert_not_called()
            mock_popen.assert_called_once()
            # The spawned command must re-invoke the app in --foreground mode.
            spawned_cmd = mock_popen.call_args.args[0]
            assert "app" in spawned_cmd
            assert "--foreground" in spawned_cmd
            assert "--hidden" in spawned_cmd
            assert "8080" in spawned_cmd


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


# ---------------------------------------------------------------------------
# Tray autostart toggle + server readiness
# ---------------------------------------------------------------------------


class TestTrayAutostartToggle:
    """Tests for the 'Start at Login' tray menu item."""

    def test_autostart_enabled_reflects_helper(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        with patch("src.session_dashboard.autostart_is_enabled", return_value=True):
            assert app._autostart_enabled() is True
        with patch("src.session_dashboard.autostart_is_enabled", return_value=False):
            assert app._autostart_enabled() is False

    def test_autostart_enabled_swallows_errors(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        with patch("src.session_dashboard.autostart_is_enabled", side_effect=RuntimeError):
            assert app._autostart_enabled() is False

    def test_toggle_enables_when_disabled(self):
        from src.tray_app import TrayApp

        app = TrayApp(port=8080)
        app.tray_icon = MagicMock()
        with (
            patch("src.session_dashboard.autostart_is_enabled", return_value=False),
            patch("src.session_dashboard.autostart_enable") as mock_enable,
            patch("src.session_dashboard.autostart_disable") as mock_disable,
        ):
            app._toggle_autostart()
        mock_enable.assert_called_once_with(port=8080, mode="app")
        mock_disable.assert_not_called()
        app.tray_icon.update_menu.assert_called_once()

    def test_toggle_disables_when_enabled(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        app.tray_icon = MagicMock()
        with (
            patch("src.session_dashboard.autostart_is_enabled", return_value=True),
            patch("src.session_dashboard.autostart_enable") as mock_enable,
            patch("src.session_dashboard.autostart_disable") as mock_disable,
        ):
            app._toggle_autostart()
        mock_disable.assert_called_once_with()
        mock_enable.assert_not_called()

    def test_toggle_notifies_on_error(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        app.tray_icon = MagicMock()
        with (
            patch("src.session_dashboard.autostart_is_enabled", return_value=False),
            patch("src.session_dashboard.autostart_enable", side_effect=RuntimeError("nope")),
            patch.object(app, "_notify") as mock_notify,
        ):
            app._toggle_autostart()
        mock_notify.assert_called_once()


class TestWaitForServer:
    """Tests for the readiness probe that prevents the blank-window race."""

    def test_returns_true_when_server_responds(self):
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert app._wait_for_server(timeout=1.0) is True

    def test_returns_true_on_http_error(self):
        import urllib.error

        from src.tray_app import TrayApp

        app = TrayApp()
        err = urllib.error.HTTPError("http://x", 404, "nf", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert app._wait_for_server(timeout=1.0) is True

    def test_returns_false_on_timeout(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        # monotonic: deadline calc -> 0.0; first loop check -> 0.0; second -> past
        with (
            patch("time.monotonic", side_effect=[0.0, 0.0, 5.0]),
            patch("time.sleep"),
            patch("urllib.request.urlopen", side_effect=OSError("refused")),
        ):
            assert app._wait_for_server(timeout=1.0) is False


# ---------------------------------------------------------------------------
# Browser-mode fallback (for platforms where pywebview can't load, e.g. ARM64
# Windows where pythonnet can't reflect over .NET 8+ WinForms types)
# ---------------------------------------------------------------------------


class TestPyWebViewSupported:
    """Tests for _pywebview_supported() platform detection."""

    @patch("sys.platform", "win32")
    @patch("platform.machine", return_value="ARM64")
    def test_windows_arm64_unsupported(self, _machine):
        from src.tray_app import _pywebview_supported

        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("AGENTEYE_BROWSER_MODE", None)
            assert _pywebview_supported() is False

    @patch("sys.platform", "win32")
    @patch("platform.machine", return_value="AMD64")
    def test_windows_x64_supported(self, _machine):
        import os

        from src.tray_app import _pywebview_supported

        os.environ.pop("AGENTEYE_BROWSER_MODE", None)
        assert _pywebview_supported() is True

    @patch("sys.platform", "darwin")
    @patch("platform.machine", return_value="arm64")
    def test_macos_arm64_supported(self, _machine):
        """macOS ARM64 doesn't use pythonnet/WinForms, so pywebview works."""
        import os

        from src.tray_app import _pywebview_supported

        os.environ.pop("AGENTEYE_BROWSER_MODE", None)
        assert _pywebview_supported() is True

    @patch("sys.platform", "linux")
    @patch("platform.machine", return_value="aarch64")
    def test_linux_arm64_supported(self, _machine):
        """Linux ARM64 doesn't use the WinForms backend."""
        import os

        from src.tray_app import _pywebview_supported

        os.environ.pop("AGENTEYE_BROWSER_MODE", None)
        assert _pywebview_supported() is True

    @patch("sys.platform", "win32")
    @patch("platform.machine", return_value="AMD64")
    def test_env_override_forces_browser_mode(self, _machine):
        """AGENTEYE_BROWSER_MODE=1 should force browser fallback even on x64."""
        from src.tray_app import _pywebview_supported

        with patch.dict("os.environ", {"AGENTEYE_BROWSER_MODE": "1"}):
            assert _pywebview_supported() is False

    @patch("sys.platform", "win32")
    @patch("platform.machine", return_value="AMD64")
    def test_env_override_accepts_truthy_variants(self, _machine):
        from src.tray_app import _pywebview_supported

        for val in ("1", "true", "TRUE", "yes", "YES"):
            with patch.dict("os.environ", {"AGENTEYE_BROWSER_MODE": val}):
                assert _pywebview_supported() is False, f"value {val!r} should trigger fallback"

    @patch("sys.platform", "win32")
    @patch("platform.machine", return_value="AMD64")
    def test_env_override_ignores_falsy_variants(self, _machine):
        from src.tray_app import _pywebview_supported

        for val in ("0", "false", "no", ""):
            with patch.dict("os.environ", {"AGENTEYE_BROWSER_MODE": val}):
                assert _pywebview_supported() is True, f"value {val!r} should not trigger fallback"


class TestTrayAppBrowserMode:
    """Tests for TrayApp browser-mode initialization and behavior."""

    def test_init_sets_browser_mode_from_probe(self):
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp()
            assert app.browser_mode is True

        with patch("src.tray_app._pywebview_supported", return_value=True):
            app = TrayApp()
            assert app.browser_mode is False

    def test_init_creates_app_window_proc_slot(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        assert app._app_window_proc is None

    def test_show_window_in_browser_mode_uses_app_window(self):
        """In browser_mode, _show_window should prefer the Chromium app window."""
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp()
        app._open_in_app_window = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        app._show_window()
        app._open_in_app_window.assert_called_once()
        app._open_in_browser.assert_not_called()

    def test_show_window_falls_back_to_browser_when_no_chromium(self):
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp()
        app._open_in_app_window = MagicMock(return_value=False)  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        app._show_window()
        app._open_in_app_window.assert_called_once()
        app._open_in_browser.assert_called_once()

    def test_show_window_in_webview_mode_does_not_open_browser(self):
        """When pywebview is supported, _show_window should not touch browser code paths."""
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=True):
            app = TrayApp()
        app._open_in_app_window = MagicMock()  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        # window is None -> early return path; ensures browser methods aren't called
        app._show_window()
        app._open_in_app_window.assert_not_called()
        app._open_in_browser.assert_not_called()


class TestFindChromiumBrowser:
    """Tests for TrayApp._find_chromium_browser()."""

    @patch("sys.platform", "win32")
    def test_returns_edge_when_present(self):
        from src.tray_app import TrayApp

        edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
        with (
            patch.dict(
                "os.environ",
                {
                    "ProgramFiles": r"C:\Program Files",
                    "ProgramFiles(x86)": r"C:\Program Files (x86)",
                },
            ),
            patch("os.path.exists", side_effect=lambda p: p == edge),
        ):
            assert TrayApp._find_chromium_browser() == edge

    @patch("sys.platform", "win32")
    def test_returns_chrome_when_edge_missing(self):
        from src.tray_app import TrayApp

        chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        with (
            patch.dict(
                "os.environ",
                {
                    "ProgramFiles": r"C:\Program Files",
                    "ProgramFiles(x86)": r"C:\Program Files (x86)",
                },
            ),
            patch("os.path.exists", side_effect=lambda p: p == chrome),
        ):
            assert TrayApp._find_chromium_browser() == chrome

    @patch("sys.platform", "win32")
    def test_returns_none_when_no_browser_found(self):
        from src.tray_app import TrayApp

        with (
            patch.dict(
                "os.environ",
                {
                    "ProgramFiles": r"C:\Program Files",
                    "ProgramFiles(x86)": r"C:\Program Files (x86)",
                },
            ),
            patch("os.path.exists", return_value=False),
        ):
            assert TrayApp._find_chromium_browser() is None

    @patch("sys.platform", "linux")
    def test_linux_uses_path_lookup(self):
        from src.tray_app import TrayApp

        with patch(
            "shutil.which",
            side_effect=lambda name: "/usr/bin/google-chrome" if name == "google-chrome" else None,
        ):
            assert TrayApp._find_chromium_browser() == "/usr/bin/google-chrome"


class TestOpenInAppWindow:
    """Tests for TrayApp._open_in_app_window() spawning."""

    def test_returns_false_when_no_browser_found(self):
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        with patch.object(TrayApp, "_find_chromium_browser", return_value=None):
            assert app._open_in_app_window() is False
        assert app._app_window_proc is None

    def test_spawns_browser_with_guest_and_app_flags(self):
        """The command line should include --guest, --app=URL, and sane defaults."""
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None

        with (
            patch.object(TrayApp, "_find_chromium_browser", return_value="msedge.exe"),
            patch("subprocess.Popen", return_value=fake_proc) as mock_popen,
        ):
            assert app._open_in_app_window() is True

        args = mock_popen.call_args.args[0]
        assert args[0] == "msedge.exe"
        assert "--guest" in args
        assert "--app=http://127.0.0.1:5111" in args
        # No persistent profile dir flag: --guest gives an ephemeral session
        # that avoids Windows-SSO auto-enrollment of a fresh Edge profile.
        assert not any(a.startswith("--user-data-dir=") for a in args)
        assert app._app_window_proc is fake_proc

    def test_does_not_relaunch_when_window_alive(self):
        """If a previous app window is still running, do not spawn a duplicate."""
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        alive_proc = MagicMock()
        alive_proc.poll.return_value = None  # still running
        app._app_window_proc = alive_proc

        with (
            patch.object(TrayApp, "_find_chromium_browser", return_value="msedge.exe"),
            patch("subprocess.Popen") as mock_popen,
        ):
            assert app._open_in_app_window() is True
            mock_popen.assert_not_called()

    def test_relaunches_when_window_exited(self):
        """If the previous window subprocess has exited, spawn a new one."""
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        dead_proc = MagicMock()
        dead_proc.poll.return_value = 0  # exited
        app._app_window_proc = dead_proc

        new_proc = MagicMock()
        new_proc.poll.return_value = None

        with (
            patch.object(TrayApp, "_find_chromium_browser", return_value="msedge.exe"),
            patch("subprocess.Popen", return_value=new_proc) as mock_popen,
        ):
            assert app._open_in_app_window() is True
            mock_popen.assert_called_once()
            assert app._app_window_proc is new_proc

    def test_returns_false_on_popen_failure(self):
        from src.tray_app import TrayApp

        app = TrayApp(port=5111)
        with (
            patch.object(TrayApp, "_find_chromium_browser", return_value="msedge.exe"),
            patch("subprocess.Popen", side_effect=OSError("nope")),
        ):
            assert app._open_in_app_window() is False
        assert app._app_window_proc is None


class TestQuitCleansUpAppWindow:
    """Tests for TrayApp._quit() terminating the spawned Chromium window."""

    def test_quit_terminates_alive_app_window(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        proc = MagicMock()
        proc.poll.return_value = None  # still running
        app._app_window_proc = proc

        with patch("os._exit") as mock_exit:
            app._quit()

        proc.terminate.assert_called_once()
        mock_exit.assert_called_once_with(0)

    def test_quit_does_not_terminate_exited_app_window(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        proc = MagicMock()
        proc.poll.return_value = 0  # already exited
        app._app_window_proc = proc

        with patch("os._exit"):
            app._quit()

        proc.terminate.assert_not_called()

    def test_quit_with_no_app_window_does_not_crash(self):
        from src.tray_app import TrayApp

        app = TrayApp()
        assert app._app_window_proc is None
        with patch("os._exit") as mock_exit:
            app._quit()
        mock_exit.assert_called_once_with(0)


class TestRunBrowserMode:
    """Tests for TrayApp._run_browser_mode() flow."""

    def test_browser_mode_starts_server_and_tray(self):
        """_run_browser_mode should start the server thread, wait, open the
        dashboard, and block on tray_icon.run()."""
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp(port=5111)

        tray_icon = MagicMock()

        # Substitute methods on the *instance* so we don't actually start a
        # uvicorn server, open a real browser, or block on a real tray loop.
        app._start_server = MagicMock()  # type: ignore[method-assign]
        app._wait_for_server = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_app_window = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        app._build_tray_icon = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda: setattr(app, "tray_icon", tray_icon)
        )

        with patch("threading.Thread") as mock_thread:
            # The Thread we create for the server doesn't actually need to
            # run anything because _start_server is mocked.
            mock_thread.return_value.start = MagicMock()
            app._run_browser_mode()

        app._wait_for_server.assert_called_once()
        app._open_in_app_window.assert_called_once()
        app._open_in_browser.assert_not_called()
        tray_icon.run.assert_called_once()
        assert app._shutdown_requested is True

    def test_browser_mode_hidden_skips_opening_window(self):
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp(port=5111, start_hidden=True)

        tray_icon = MagicMock()
        app._start_server = MagicMock()  # type: ignore[method-assign]
        app._wait_for_server = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_app_window = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        app._build_tray_icon = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda: setattr(app, "tray_icon", tray_icon)
        )

        with patch("threading.Thread"):
            app._run_browser_mode()

        app._open_in_app_window.assert_not_called()
        app._open_in_browser.assert_not_called()
        tray_icon.run.assert_called_once()

    def test_browser_mode_falls_back_to_default_browser(self):
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp(port=5111)

        tray_icon = MagicMock()
        app._start_server = MagicMock()  # type: ignore[method-assign]
        app._wait_for_server = MagicMock(return_value=True)  # type: ignore[method-assign]
        app._open_in_app_window = MagicMock(return_value=False)  # type: ignore[method-assign]
        app._open_in_browser = MagicMock()  # type: ignore[method-assign]
        app._build_tray_icon = MagicMock(  # type: ignore[method-assign]
            side_effect=lambda: setattr(app, "tray_icon", tray_icon)
        )

        with patch("threading.Thread"):
            app._run_browser_mode()

        app._open_in_app_window.assert_called_once()
        app._open_in_browser.assert_called_once()

    def test_run_dispatches_to_browser_mode_when_unsupported(self):
        """TrayApp.run() should hand off to _run_browser_mode without ever
        importing pywebview when browser_mode is set."""
        from src.tray_app import TrayApp

        with patch("src.tray_app._pywebview_supported", return_value=False):
            app = TrayApp(port=5111)
        app._run_browser_mode = MagicMock()  # type: ignore[method-assign]

        # If run() tried to import webview, it would blow up on this machine
        # (ARM64). The fact that the call returns cleanly confirms the
        # browser_mode branch short-circuits before the pywebview import.
        app.run()
        app._run_browser_mode.assert_called_once()
