"""
System tray application for Agent Eye.

Provides a native system tray icon with a PyWebView window for the dashboard.
The server runs in-process and stays alive as long as the tray app is running.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pystray import Icon

# ctypes is imported unconditionally above because the module exists on all
# platforms; only Windows-specific parts (ctypes.wintypes, ctypes.windll) are
# guarded by a runtime win32 check.
# DWM constant for dark title bar (used only on Windows)
DWMWA_USE_IMMERSIVE_DARK_MODE = 20

# Platform-specific imports
if sys.platform == "win32":
    import ctypes.wintypes

if sys.platform == "darwin":
    try:
        from AppKit import NSApplication, NSImage  # type: ignore[import-not-found]

        _HAS_APPKIT = True
    except ImportError:
        _HAS_APPKIT = False
        NSApplication = None  # type: ignore[misc, assignment]
        NSImage = None  # type: ignore[misc, assignment]
else:
    _HAS_APPKIT = False
    NSApplication = None  # type: ignore[misc, assignment]
    NSImage = None  # type: ignore[misc, assignment]


def _pywebview_supported() -> bool:
    """Return False when pywebview is known to be unusable on this platform.

    The WinForms backend that pywebview uses on Windows depends on pythonnet
    successfully reflecting over `System.Windows.Forms` and several private
    internal types (`FileDialogNative+IFileDialog`, etc.) that were removed in
    .NET Core+. On x64 Windows pythonnet loads `netfx` (the .NET Framework
    GAC), where those types still exist, so everything works. On ARM64 Windows
    .NET Framework does not exist at all, pythonnet falls back to coreclr, and
    pywebview's WinForms backend cannot initialize. See pywebview PR #1803.

    Until that is fixed upstream, fall back to opening the dashboard in the
    user's default browser. Override with `AGENTEYE_BROWSER_MODE=1` to force
    browser mode on other platforms (useful for headless / SSH scenarios).
    """
    import os
    import platform

    if os.environ.get("AGENTEYE_BROWSER_MODE", "").lower() in ("1", "true", "yes"):
        return False
    if sys.platform == "win32" and platform.machine().lower() in ("arm64", "aarch64"):
        return False
    return True


def _set_dark_title_bar(hwnd: int, dark: bool = True) -> None:
    """Enable or disable dark title bar on Windows.

    Args:
        hwnd: Window handle
        dark: True for dark mode, False for light mode
    """
    if sys.platform != "win32" or not hwnd:
        return
    try:
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        pass  # Silently fail if we can't set dark mode


def _get_window_hwnd() -> int | None:
    """Get the window handle for the Agent Eye window."""
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.user32.FindWindowW(None, "Agent Eye")
    except Exception:
        return None


class WindowApi:
    """API exposed to JavaScript in the webview."""

    def __init__(self, tray_app: TrayApp):
        self._tray_app = tray_app

    def set_theme(self, theme: str) -> None:
        """Set the title bar theme. Called from JS when theme changes.

        Args:
            theme: 'dark' or 'light'
        """
        hwnd = _get_window_hwnd()
        if hwnd:
            _set_dark_title_bar(hwnd, dark=(theme == "dark"))
        _set_macos_title_bar(dark=(theme == "dark"))

    def send_notification(self, title: str, body: str) -> bool:
        """Send a native notification via plyer.

        Args:
            title: Notification title
            body: Notification body text

        Returns:
            True if notification was sent, False otherwise
        """
        try:
            from plyer import notification

            # Get icon path for notification
            icon_path = _get_window_icon_path()
            notification.notify(
                title=title,
                message=body,
                app_name="Agent Eye",
                app_icon=str(icon_path) if icon_path.exists() else None,
                timeout=5,
            )
            return True
        except Exception:
            # Fallback to pystray notify
            if self._tray_app.tray_icon:
                try:
                    self._tray_app.tray_icon.notify(body, title)
                    return True
                except Exception:
                    pass
        return False

    def is_native_app(self) -> bool:
        """Check if running as native app (vs browser)."""
        return True


def _get_tray_icon_path() -> Path:
    """Get the path to the tray icon file for the current platform."""
    static_dir = Path(__file__).parent / "static"

    if sys.platform == "win32":
        # Windows: prefer .ico
        ico_path = static_dir / "tray-icon.ico"
        if ico_path.exists():
            return ico_path
        return static_dir / "tray-icon.png"
    elif sys.platform == "darwin":
        # macOS: use template image for menu bar
        template_path = static_dir / "trayTemplate.png"
        if template_path.exists():
            return template_path
        return static_dir / "icon-512.png"
    else:
        # Linux: use PNG
        png_path = static_dir / "tray-icon.png"
        if png_path.exists():
            return png_path
        return static_dir / "icon-512.png"


def _get_window_icon_path() -> Path:
    """Get the path to the window/taskbar icon."""
    static_dir = Path(__file__).parent / "static"
    if sys.platform == "win32":
        # Windows needs .ico for window icon
        ico_path = static_dir / "tray-icon.ico"
        if ico_path.exists():
            return ico_path
    return static_dir / "icon-512.png"


def _set_macos_dock_icon(icon_path: Path) -> None:
    """Set the dock icon on macOS using AppKit."""
    if not _HAS_APPKIT or NSApplication is None or NSImage is None:
        return
    try:
        app = NSApplication.sharedApplication()
        img = NSImage.alloc().initByReferencingFile_(str(icon_path))
        if img:
            app.setApplicationIconImage_(img)
    except Exception:
        pass  # Silently fail if we can't set the icon


def _set_macos_dock_visible(visible: bool) -> None:
    """Show or hide the dock icon on macOS via the app activation policy.

    A tray app should behave like a menu-bar utility: the dock icon appears while
    the window is open and disappears when minimized to the tray. We toggle the
    NSApplication activation policy (Regular shows the dock icon, Accessory hides
    it). Must be called on the main thread.
    """
    if sys.platform != "darwin" or not _HAS_APPKIT or NSApplication is None:
        return
    try:
        app = NSApplication.sharedApplication()
        # NSApplicationActivationPolicyRegular = 0, Accessory = 1
        app.setActivationPolicy_(0 if visible else 1)
        if visible:
            app.activateIgnoringOtherApps_(True)
    except Exception:
        pass  # Silently fail if we can't change the policy


def _set_macos_title_bar(dark: bool) -> None:
    """Match the native window title bar to the app's dark/light theme on macOS.

    The title bar follows the NSWindow ``appearance``. We locate the dashboard
    window by title and set DarkAqua or Aqua. AppKit calls must run on the main
    thread, so the work is dispatched there (this is typically invoked from the
    pywebview JS bridge thread).
    """
    if sys.platform != "darwin" or not _HAS_APPKIT or NSApplication is None:
        return
    try:
        from AppKit import NSAppearance  # type: ignore[import-not-found]
        from PyObjCTools import AppHelper  # type: ignore[import-not-found]
    except Exception:
        return

    def _apply() -> None:
        try:
            name = "NSAppearanceNameDarkAqua" if dark else "NSAppearanceNameAqua"
            appearance = NSAppearance.appearanceNamed_(name)
            app = NSApplication.sharedApplication()
            for win in app.windows():
                try:
                    if win.title() == "Agent Eye":
                        win.setAppearance_(appearance)
                except Exception:
                    pass
        except Exception:
            pass

    try:
        AppHelper.callAfter(_apply)
    except Exception:
        _apply()


def _set_macos_app_name(name: str) -> None:
    """Set the application name shown in the dock and menu bar on macOS.

    When launched via ``python -m`` the process is unbundled, so macOS shows
    "Python". Overriding ``CFBundleName`` in the main bundle's info dictionary
    makes the dock tooltip and app menu display a friendly name instead.
    """
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle  # type: ignore[import-not-found]

        bundle = NSBundle.mainBundle()
        if bundle is None:
            return
        info = bundle.localizedInfoDictionary() or bundle.infoDictionary()
        if info is not None:
            info["CFBundleName"] = name
            info["CFBundleDisplayName"] = name
    except Exception:
        pass  # Silently fail if we can't set the name


class TrayApp:
    """System tray application with embedded dashboard."""

    def __init__(self, port: int = 5111, log_level: str | None = None, start_hidden: bool = False):
        self.port = port
        self.log_level = log_level
        self.start_hidden = start_hidden
        self.window: Any = None
        self.tray_icon: Icon | None = None
        self.server_thread: threading.Thread | None = None
        self._server_started = threading.Event()
        self._shutdown_requested = False
        self._webview_module: Any = None
        self.browser_mode: bool = not _pywebview_supported()
        # Process handle for the Edge/Chrome --app=URL window used in
        # browser_mode, so the tray "Show Dashboard" action can avoid spawning
        # a duplicate window when one is already open.
        self._app_window_proc: Any = None

    def _start_server(self) -> None:
        """Start the FastAPI server in a background thread."""
        import uvicorn

        from .logging_config import setup_logging
        from .sync import resolve_sync_folder

        setup_logging(level=self.log_level)

        # Log sync folder info
        sync_folder = resolve_sync_folder()
        if sync_folder:
            print(f"  [sync] Sync folder: {sync_folder}")
        else:
            print("  [sync] Sync: disabled")

        # Signal that we're about to start
        self._server_started.set()

        # Run uvicorn - this blocks until shutdown
        config = uvicorn.Config(
            "src.dashboard_api:app",
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        server.run()

    def _wait_for_server(self, timeout: float = 20.0) -> bool:
        """Poll the local HTTP server until it responds or the timeout elapses.

        Returns True once the server answers, False if it never came up within
        ``timeout`` seconds. Avoids loading the webview against a not-yet-bound
        server, which renders as a blank white page.
        """
        import time
        import urllib.error
        import urllib.request

        url = f"http://127.0.0.1:{self.port}/"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=1.0) as resp:
                    if resp.status < 500:
                        return True
            except urllib.error.HTTPError:
                # Any HTTP response means the server is up and routing.
                return True
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(0.2)
        return False

    def _on_window_close(self) -> bool:
        """Handle window close - hide instead of destroy (minimize to tray).

        pywebview cancels the close when a ``closing`` handler returns ``False``,
        so we return ``False`` to keep the app alive and hide to the tray. During
        an actual quit we return ``True`` to allow the window to be destroyed.
        """
        if self.window and not self._shutdown_requested:
            # Hide window instead of closing - this minimizes to tray
            self.window.hide()
            _set_macos_dock_visible(False)  # Drop dock icon while in the tray
            return False  # Return False to CANCEL the close (keep app running)
        return True  # Allow close during shutdown

    def _toggle_window(self) -> None:
        """Toggle window visibility (show if hidden, hide if shown)."""
        if self.browser_mode:
            self._show_window()
            return
        if not self.window:
            return
        # pywebview doesn't expose visibility state, so we just show
        self._show_window()

    def _show_window(self) -> None:
        """Show and focus the dashboard window."""
        if self.browser_mode:
            # No native window in browser mode — open in a Chromium app-mode
            # (frameless) window when possible to mimic the embedded webview
            # experience, falling back to a regular browser tab otherwise.
            if not self._open_in_app_window():
                self._open_in_browser()
            return
        if self.window:
            _set_macos_dock_visible(True)  # Restore dock icon when window is shown
            # Re-assert our custom dock icon: when the app started hidden the icon
            # was set while it had no dock entry, so macOS would otherwise fall
            # back to the default Python rocket once the dock icon reappears.
            if sys.platform == "darwin":
                _set_macos_dock_icon(_get_window_icon_path())
            self.window.show()
            self.window.restore()  # Unminimize if minimized
            # Bring to front
            if hasattr(self.window, "on_top"):
                self.window.on_top = True
                self.window.on_top = False

    def _hide_window(self) -> None:
        """Hide the dashboard window (minimize to tray)."""
        if self.window:
            self.window.hide()
            _set_macos_dock_visible(False)  # Drop dock icon while in the tray

    def _open_in_browser(self) -> None:
        """Open the dashboard in the default browser."""
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{self.port}")

    def _open_in_app_window(self) -> bool:
        """Open the dashboard in a Chromium app-mode (frameless) window.

        Uses Edge or Chrome's ``--app=URL`` with a dedicated user-data-dir so
        the window opens standalone instead of joining the user's normal
        browsing session. Returns True if an app window was successfully
        spawned (or one is already alive); False if no suitable browser was
        found and the caller should fall back to a regular browser tab.
        """
        import subprocess

        # If a previously spawned app window is still alive, do nothing -
        # bringing it to front from outside the process is non-trivial and a
        # second --app launch would just open a second window.
        if self._app_window_proc is not None and self._app_window_proc.poll() is None:
            return True

        browser_path = self._find_chromium_browser()
        if not browser_path:
            return False

        url = f"http://127.0.0.1:{self.port}"
        # --guest gives an ephemeral session: no sign-in, no sync, no profile
        # persistence. Avoids Edge's Windows-SSO auto-enrolling the profile
        # into the user's work account. Theme/localStorage are lost between
        # launches, but for a local dashboard that's an acceptable trade.
        cmd = [
            browser_path,
            "--guest",
            f"--app={url}",
            "--window-size=1200,800",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NO_WINDOW so the browser survives
            # independently and we don't flash a console.
            kwargs["creationflags"] = 0x00000008 | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True

        try:
            self._app_window_proc = subprocess.Popen(cmd, **kwargs)
            return True
        except Exception:
            self._app_window_proc = None
            return False

    @staticmethod
    def _find_chromium_browser() -> str | None:
        """Locate a Chromium-based browser executable for ``--app`` mode.

        Prefers Edge (always present on modern Windows), then Chrome, then
        Brave. Returns None on platforms / installs without one.
        """
        candidates: list[str] = []
        if sys.platform == "win32":
            pf = os.environ.get("ProgramFiles", r"C:\Program Files")
            pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
            local = os.environ.get("LOCALAPPDATA", "")
            candidates = [
                rf"{pf}\Microsoft\Edge\Application\msedge.exe",
                rf"{pf86}\Microsoft\Edge\Application\msedge.exe",
                rf"{pf}\Google\Chrome\Application\chrome.exe",
                rf"{pf86}\Google\Chrome\Application\chrome.exe",
                rf"{local}\Google\Chrome\Application\chrome.exe",
                rf"{local}\Microsoft\Edge\Application\msedge.exe",
            ]
        elif sys.platform == "darwin":
            candidates = [
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
        else:
            for name in ("microsoft-edge", "google-chrome", "chromium", "brave-browser"):
                found = shutil.which(name)
                if found:
                    return found
        for c in candidates:
            if c and os.path.exists(c):
                return c
        return None

    def _quit(self) -> None:
        """Quit the application completely."""
        import os

        self._shutdown_requested = True

        # Hide window immediately for snappy feel
        if self.window:
            try:
                self.window.hide()
            except Exception:
                pass

        # Close the Chromium app-mode window if we spawned one (browser_mode).
        if self._app_window_proc is not None and self._app_window_proc.poll() is None:
            try:
                self._app_window_proc.terminate()
            except Exception:
                pass

        # Stop the tray icon
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        # Force exit
        os._exit(0)

    def _autostart_enabled(self) -> bool:
        """Return whether login autostart is currently configured."""
        try:
            from .session_dashboard import autostart_is_enabled

            return autostart_is_enabled()
        except Exception:
            return False

    def _toggle_autostart(self) -> None:
        """Enable/disable launching Agent Eye at login from the tray."""
        from .session_dashboard import (
            autostart_disable,
            autostart_enable,
            autostart_is_enabled,
        )

        try:
            if autostart_is_enabled():
                autostart_disable()
                enabled = False
            else:
                autostart_enable(port=self.port, mode="app")
                enabled = True
        except Exception as e:
            self._notify("Agent Eye", f"Could not change startup setting: {e}")
            return

        # Refresh the checkmark and let the user know.
        if self.tray_icon:
            try:
                self.tray_icon.update_menu()
            except Exception:
                pass
        self._notify(
            "Agent Eye",
            "Will start at login." if enabled else "Will no longer start at login.",
        )

    def _notify(self, title: str, body: str) -> None:
        """Best-effort tray notification (silently ignores failures)."""
        if self.tray_icon:
            try:
                self.tray_icon.notify(body, title)
            except Exception:
                pass

    def _create_tray_menu(self) -> Any:
        """Create the system tray context menu."""
        import pystray

        return pystray.Menu(
            pystray.MenuItem(
                "Show Dashboard",
                lambda: self._show_window(),
                default=True,  # Double-click action
            ),
            pystray.MenuItem("Hide to Tray", lambda: self._hide_window()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open in Browser", lambda: self._open_in_browser()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start at Login",
                lambda: self._toggle_autostart(),
                checked=lambda item: self._autostart_enabled(),
            ),
            pystray.MenuItem(f"Port: {self.port}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self._quit()),
        )

    def _build_tray_icon(self) -> None:
        """Construct the pystray icon.

        On macOS this must be called on the main thread because pystray creates
        the underlying NSStatusItem in the Icon constructor, and AppKit requires
        UI objects to be instantiated on the main thread.
        """
        import pystray
        from PIL import Image

        icon_path = _get_tray_icon_path()

        try:
            icon_image: Any = Image.open(icon_path)
        except Exception:
            # Create a simple fallback icon (blue square with white center)
            icon_image = Image.new("RGBA", (64, 64), color=(66, 133, 244, 255))

        self.tray_icon = pystray.Icon(
            name="agenteye",
            icon=icon_image,
            title="Agent Eye",
            menu=self._create_tray_menu(),
        )

    def _run_tray(self) -> None:
        """Build and run the system tray icon (blocking)."""
        self._build_tray_icon()
        assert self.tray_icon is not None
        self.tray_icon.run()

    def _run_browser_mode(self) -> None:
        """Run as a tray-only app, opening the dashboard in the default browser.

        Used on platforms where pywebview's WinForms backend can't initialize
        (currently: Windows ARM64; see _pywebview_supported). The local server
        still runs in this process; the tray icon keeps it alive and exposes
        the same menu (Show Dashboard, Open in Browser, Start at Login, Quit).
        """
        # Tell the API which autostart mode best matches how we're running.
        # In browser_mode the embedded webview is unavailable, so autostart
        # should use the lighter headless "server" command - matching what
        # the user expects when they toggle "Start at Login" from the page.
        try:
            from . import dashboard_api

            dashboard_api.LAUNCH_MODE = "server"
        except Exception:
            pass

        # Windows-specific identity setup, same as the webview path.
        if sys.platform == "win32":
            app_id = "CopilotDashboard.App.1"
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
            except Exception:
                pass
            try:
                import winreg

                key_path = rf"SOFTWARE\Classes\AppUserModelId\{app_id}"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Agent Eye")
                    icon_path = _get_window_icon_path()
                    if icon_path.exists():
                        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
            except Exception:
                pass

        from .__version__ import __version__

        print(f"  Agent Eye v{__version__} (Tray App, browser mode)")
        print(f"  Starting on http://127.0.0.1:{self.port}")
        print()
        print("  Embedded webview is not available on this platform.")
        print("  The dashboard will open in your default browser.")
        print("  - Right-click tray icon -> Show Dashboard = re-open in browser")
        print("  - Right-click tray icon -> Quit = exit completely")
        print()

        # Start the server in a background thread.
        self.server_thread = threading.Thread(target=self._start_server, daemon=True)
        self.server_thread.start()
        self._server_started.wait(timeout=5)
        self._wait_for_server(timeout=20.0)

        print("  Dashboard ready!")

        # Open the dashboard in a Chromium app-mode window (frameless,
        # no toolbars - looks like a native app) unless start_hidden. Falls
        # back to a regular browser tab if no Chromium-based browser is found.
        if not self.start_hidden:
            if not self._open_in_app_window():
                self._open_in_browser()
        else:
            print("  (Started hidden - click tray icon to open the dashboard)")

        # Build and run the tray icon (blocking until Quit).
        self._build_tray_icon()
        assert self.tray_icon is not None
        self.tray_icon.run()

        self._shutdown_requested = True

    def run(self) -> None:
        """Run the tray application."""
        if self.browser_mode:
            self._run_browser_mode()
            return

        # Tray-with-embedded-webview mode: tell the API which autostart command
        # matches this launch so the dashboard's "Start at Login" toggle
        # restarts the same way.
        try:
            from . import dashboard_api

            dashboard_api.LAUNCH_MODE = "app"
        except Exception:
            pass

        import webview

        # Set the dock/menu-bar app name on macOS (otherwise shows "Python")
        if sys.platform == "darwin":
            _set_macos_app_name("Agent Eye")

        # Set Windows AppUserModelID so taskbar shows our icon, not Python's
        if sys.platform == "win32":
            app_id = "CopilotDashboard.App.1"
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
            except Exception:
                pass

            # Register display name for toast notifications
            try:
                import winreg

                key_path = rf"SOFTWARE\Classes\AppUserModelId\{app_id}"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Agent Eye")
                    icon_path = _get_window_icon_path()
                    if icon_path.exists():
                        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
            except Exception:
                pass

        self._webview_module = webview

        from .__version__ import __version__

        print(f"  Agent Eye v{__version__} (Tray App)")
        print(f"  Starting on http://127.0.0.1:{self.port}")
        print()
        print("  - Close window (X) = minimize to tray")
        print("  - Right-click tray icon -> Quit = exit completely")
        print()

        # Set macOS dock icon before creating windows
        if sys.platform == "darwin":
            _set_macos_dock_icon(_get_window_icon_path())

        # Start the server in a background thread
        self.server_thread = threading.Thread(target=self._start_server, daemon=True)
        self.server_thread.start()

        # Wait for the server thread to spin up, then poll until the HTTP
        # server is actually accepting requests. The webview has no built-in
        # retry, so loading the URL before uvicorn has bound shows a blank
        # white page (common on a cold first launch where importing the API
        # module takes longer than a fixed sleep).
        self._server_started.wait(timeout=5)
        self._wait_for_server(timeout=20.0)

        # Start the tray icon. On macOS the NSStatusItem must be created on the
        # main thread and shares the NSApplication run loop with pywebview, so we
        # build it here and run it detached (pywebview's loop drives it). On other
        # platforms pystray runs its own loop in a background thread.
        if sys.platform == "darwin":
            self._build_tray_icon()
            assert self.tray_icon is not None
            self.tray_icon.run_detached()
        else:
            tray_thread = threading.Thread(target=self._run_tray, daemon=True)
            tray_thread.start()

        # Create the webview window (hidden if start_hidden)
        # Pass the API for JS to call back into Python
        self.window = webview.create_window(
            title="Agent Eye",
            url=f"http://127.0.0.1:{self.port}",
            width=1200,
            height=800,
            min_size=(800, 600),
            hidden=self.start_hidden,
            js_api=WindowApi(self),
        )

        # Set close handler - hide instead of quit
        self.window.events.closing += self._on_window_close

        # Set initial dark title bar after window is shown
        def on_shown():
            hwnd = _get_window_hwnd()
            if hwnd:
                _set_dark_title_bar(hwnd, dark=True)  # Default to dark
            _set_macos_title_bar(dark=True)  # Default to dark (frontend resyncs)

        self.window.events.shown += on_shown

        # On macOS, start without a dock icon when launched hidden to the tray.
        # pywebview resets the activation policy to Regular during webview.start(),
        # so a synchronous call here would be overridden. Defer the Accessory
        # switch onto the main run loop, just after the event loop comes up.
        if sys.platform == "darwin" and self.start_hidden:

            def _defer_hide_dock() -> None:
                import time as _time

                _time.sleep(0.8)  # let pywebview finish initializing the app
                try:
                    from PyObjCTools import AppHelper  # type: ignore[import-not-found]

                    AppHelper.callAfter(lambda: _set_macos_dock_visible(False))
                except Exception:
                    _set_macos_dock_visible(False)

            threading.Thread(target=_defer_hide_dock, daemon=True).start()

        print("  Dashboard ready!")
        if self.start_hidden:
            print("  (Window hidden - click tray icon to show)")

        # Start the webview event loop with icon (this blocks until window is destroyed)
        icon_path = _get_window_icon_path()
        webview.start(icon=str(icon_path) if icon_path.exists() else None)

        # Clean up after webview exits (only happens on actual quit)
        self._shutdown_requested = True
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass


def run_tray_app(
    port: int = 5111, log_level: str | None = None, start_hidden: bool = False
) -> None:
    """Entry point to run the tray application."""
    app = TrayApp(port=port, log_level=log_level, start_hidden=start_hidden)
    app.run()
