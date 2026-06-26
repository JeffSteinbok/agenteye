"""
System tray application for Copilot Dashboard.

Provides a native system tray icon with a PyWebView window for the dashboard.
The server runs in-process and stays alive as long as the tray app is running.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pystray import Icon

# Platform-specific imports
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes

    # DWM constants for dark title bar
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20

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
    """Get the window handle for the Copilot Dashboard window."""
    if sys.platform != "win32":
        return None
    try:
        return ctypes.windll.user32.FindWindowW(None, "Copilot Dashboard")
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
                app_name="Copilot Dashboard",
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

    def _on_window_close(self) -> bool:
        """Handle window close - hide instead of destroy (minimize to tray)."""
        if self.window and not self._shutdown_requested:
            # Hide window instead of closing - this minimizes to tray
            self.window.hide()
            return True  # Return True to PREVENT window destruction
        return False  # Allow close during shutdown

    def _toggle_window(self) -> None:
        """Toggle window visibility (show if hidden, hide if shown)."""
        if not self.window:
            return
        # pywebview doesn't expose visibility state, so we just show
        self._show_window()

    def _show_window(self) -> None:
        """Show and focus the dashboard window."""
        if self.window:
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

    def _open_in_browser(self) -> None:
        """Open the dashboard in the default browser."""
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{self.port}")

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

        # Stop the tray icon
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        # Force exit
        os._exit(0)

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
            pystray.MenuItem(f"Port: {self.port}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: self._quit()),
        )

    def _run_tray(self) -> None:
        """Run the system tray icon."""
        import pystray
        from PIL import Image

        icon_path = _get_tray_icon_path()

        try:
            icon_image: Any = Image.open(icon_path)
        except Exception:
            # Create a simple fallback icon (blue square with white center)
            icon_image = Image.new("RGBA", (64, 64), color=(66, 133, 244, 255))

        self.tray_icon = pystray.Icon(
            name="copilot-dashboard",
            icon=icon_image,
            title="Copilot Dashboard",
            menu=self._create_tray_menu(),
        )

        self.tray_icon.run()

    def run(self) -> None:
        """Run the tray application."""
        import webview

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
                    winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Copilot Dashboard")
                    icon_path = _get_window_icon_path()
                    if icon_path.exists():
                        winreg.SetValueEx(key, "IconUri", 0, winreg.REG_SZ, str(icon_path))
            except Exception:
                pass

        self._webview_module = webview

        from .__version__ import __version__

        print(f"  Copilot Dashboard v{__version__} (Tray App)")
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

        # Wait for server to start
        self._server_started.wait(timeout=5)

        # Give the server a moment to actually bind
        import time

        time.sleep(0.5)

        # Start the tray icon in a background thread
        tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        tray_thread.start()

        # Create the webview window (hidden if start_hidden)
        # Pass the API for JS to call back into Python
        self.window = webview.create_window(
            title="Copilot Dashboard",
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

        self.window.events.shown += on_shown

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
