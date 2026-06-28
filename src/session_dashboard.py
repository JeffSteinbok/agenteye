"""
Agent Eye - CLI entry point.
Provides start, stop, and status subcommands.
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.request

from .constants import (
    DASHBOARD_LOG_FILE,
    DEFAULT_PORT,
    LOCALHOST,
    MIN_PYTHON_VERSION,
    PYTHON_VERSION_TIMEOUT,
)
from .logging_config import setup_logging

PKG_DIR = os.path.dirname(os.path.abspath(__file__))

from .__version__ import __repository__, __version__  # noqa: E402

BANNER = f"""\
  Agent Eye v{__version__}
  By Jeff Steinbok — {__repository__}
  Open http://localhost:{{port}}
  Log file: {DASHBOARD_LOG_FILE}
"""


def _print_sync_info(sync_folder) -> None:  # type: ignore[no-untyped-def]
    """Print sync folder status on startup."""
    if sync_folder:
        print(f"  [sync] Sync folder: {sync_folder}")
        print('     Configure: set "sync.folder" in ~/.copilot/dashboard-config.json')
        print('     Disable:   set "sync.enabled" to false in ~/.copilot/dashboard-config.json')
    else:
        print("  [sync] Sync: disabled (no OneDrive/cloud folder detected)")
        print(
            '     Enable: set "sync.folder" to a cloud-synced path'
            " in ~/.copilot/dashboard-config.json"
        )
    print()


def _probe_server(port: int) -> dict | None:
    """Probe a running dashboard server on the given port.

    Returns a dict with ``pid``, ``port``, and (if available) ``sync_folder``,
    or *None* if nothing is listening.
    """
    try:
        url = f"http://{LOCALHOST}:{port}/api/server-info"
        with urllib.request.urlopen(url, timeout=2) as resp:
            data: dict = json.loads(resp.read())
            return data
    except Exception:
        return None


def _kill_pid(pid: int) -> None:
    """Terminate a process by PID, cross-platform."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
    else:
        os.kill(pid, signal.SIGTERM)


def _find_python():
    """Find a suitable Python interpreter, preferring the py launcher on Windows.

    Returns a list of command parts (e.g. ["py", "-3"] or ["/usr/bin/python3.13"]).
    """
    if sys.version_info >= MIN_PYTHON_VERSION:
        return [sys.executable]

    # Try the py launcher (Windows)
    py = shutil.which("py")
    if py:
        try:
            result = subprocess.run(
                [py, "-3", "--version"],
                capture_output=True,
                text=True,
                timeout=PYTHON_VERSION_TIMEOUT,
                check=False,
            )
            if result.returncode == 0:
                ver = result.stdout.strip().split()[-1]  # "3.14.3"
                major, minor = (int(x) for x in ver.split(".")[:2])
                if major >= MIN_PYTHON_VERSION[0] and minor >= MIN_PYTHON_VERSION[1]:
                    return [py, "-3"]
        except Exception:
            pass

    # Fallback: search PATH for python3.x
    for minor in range(14, 10, -1):
        candidate = shutil.which(f"python3.{minor}")
        if candidate:
            return [candidate]

    return [sys.executable]


def cmd_serve(args):
    """Internal: run the uvicorn server in-process (used by --background)."""
    import uvicorn

    from .sync import resolve_sync_folder

    _migrate_autostart()
    setup_logging(level=getattr(args, "log_level", None))
    _print_sync_info(resolve_sync_folder())
    uvicorn.run(
        "src.dashboard_api:app",
        host=LOCALHOST,
        port=args.port,
        log_level="warning",
    )


def cmd_start(args):
    """Start the dashboard server."""
    info = _probe_server(args.port)
    if info:
        pid = info.get("pid", "?")
        print(f"Dashboard already running (PID {pid}) at http://localhost:{args.port}")
        return

    if args.background:
        python = _find_python()
        log_level = getattr(args, "log_level", None)
        pkg = __spec__.parent if __spec__ else None
        if pkg:
            repo_root = os.path.dirname(PKG_DIR)
            cmd = [
                *python,
                "-m",
                f"{pkg}.session_dashboard",
                "_serve",
                "--port",
                str(args.port),
            ]
        else:
            cmd = [
                *python,
                "-m",
                "src.session_dashboard",
                "_serve",
                "--port",
                str(args.port),
            ]
            repo_root = os.path.dirname(PKG_DIR)
        if log_level:
            cmd.extend(["--log-level", log_level])
        subprocess.Popen(  # pylint: disable=consider-using-with
            cmd,
            cwd=repo_root,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(BANNER.format(port=args.port))

        # Wait briefly for the server to come up
        import time

        for _ in range(5):
            time.sleep(0.5)
            if _probe_server(args.port):
                info = _probe_server(args.port)
                pid = info.get("pid", "?") if info else "?"
                print(f"Dashboard started (PID {pid}) at http://localhost:{args.port}")
                return
        print(
            "Dashboard process launched but server not yet responding.\n"
            "  Try: agenteye status --port " + str(args.port)
        )
    else:
        import uvicorn

        from .sync import resolve_sync_folder

        _migrate_autostart()
        setup_logging(level=getattr(args, "log_level", None))
        print(BANNER.format(port=args.port))
        _print_sync_info(resolve_sync_folder())
        uvicorn.run(
            "src.dashboard_api:app",
            host=LOCALHOST,
            port=args.port,
            log_level="warning",
        )


def cmd_stop(args):
    """Stop the dashboard server."""
    port = args.port
    info = _probe_server(port)
    if not info:
        print(f"Dashboard is not running on port {port}.")
        return

    pid = info.get("pid")
    if not pid:
        print(f"Dashboard responded on port {port} but did not report a PID.")
        return

    try:
        _kill_pid(pid)
        print(f"Dashboard stopped (PID {pid}, port {port}).")
    except Exception as e:
        print(f"Could not stop process {pid}: {e}")


def cmd_upgrade(args):
    """Upgrade the dashboard via pip and restart if it was running."""
    from .__version__ import __version__ as old_version

    port = args.port
    info = _probe_server(port)
    was_running = info is not None

    # Stop the server first to release file locks (important on Windows)
    if was_running:
        pid = info.get("pid")  # type: ignore[union-attr]
        print(f"Stopping dashboard (PID {pid})...")
        try:
            if pid:
                _kill_pid(pid)
        except Exception:
            pass

    # Run pip upgrade
    print("Upgrading agenteye...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--upgrade",
            "agenteye",
        ],
        check=False,
    )
    if result.returncode != 0:
        print("Upgrade failed.")
        return

    # Report version change
    try:
        ver_out = subprocess.run(
            [sys.executable, "-c", "from src.__version__ import __version__; print(__version__)"],
            capture_output=True,
            text=True,
            check=False,
        )
        new_version = ver_out.stdout.strip() if ver_out.returncode == 0 else "unknown"
    except Exception:
        new_version = "unknown"
    print(f"Upgraded: v{old_version} -> v{new_version}")

    # Restart if it was running
    if was_running:
        print(f"Restarting dashboard on port {port}...")
        cmd = shutil.which("agenteye")
        if cmd:
            kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | 0x00000008
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen([cmd, "start", "--background", "--port", str(port)], **kwargs)
            print(f"Dashboard restarted at http://localhost:{port}")
            print("Please refresh your browser to pick up the new version.")
        else:
            print("Could not find agenteye command to restart. Start it manually.")


def cmd_status(args):
    """Check if the dashboard is running."""
    port = args.port
    info = _probe_server(port)
    if info:
        pid = info.get("pid", "?")
        print(f"Dashboard is running (PID {pid}) on port {port}")
    else:
        print(f"Dashboard is not running on port {port}.")


TASK_NAME = "AgentEye"
"""Windows registry value name under HKCU\\...\\Run for autostart."""
OLD_TASK_NAME = "CopilotDashboard"
"""Legacy Windows Run value name; migrated to TASK_NAME at startup."""
OLD_MACOS_LAUNCH_AGENT_LABEL = "com.copilotdashboard.app"
"""Legacy macOS LaunchAgent label cleaned up during migration."""

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_autostart_cmd_str(port: int, mode: str = "server") -> str:
    """Build the command string for the Run registry value.

    Args:
        port: Port number to use.
        mode: Either "server" (headless background) or "app" (tray app with window).
    """
    cmd = shutil.which("agenteye")
    if mode == "app":
        # Start hidden on login - user can click tray icon to show
        if cmd:
            return f'"{cmd}" app --hidden --port {port}'
        return f'"{sys.executable}" -m src.session_dashboard app --hidden --port {port}'
    else:
        if cmd:
            return f'"{cmd}" start --background --port {port}'
        return f'"{sys.executable}" -m src.session_dashboard start --background --port {port}'


# ── macOS autostart (LaunchAgent) ────────────────────────────────────────────

MACOS_LAUNCH_AGENT_LABEL = "com.agenteye.app"
"""Reverse-DNS label for the macOS LaunchAgent plist."""


def _macos_plist_path() -> str:
    """Path to the per-user LaunchAgent plist for the dashboard."""
    return os.path.expanduser(f"~/Library/LaunchAgents/{MACOS_LAUNCH_AGENT_LABEL}.plist")


def _get_autostart_program_args(port: int, mode: str = "server") -> list[str]:
    """Build the LaunchAgent ProgramArguments for macOS.

    Uses the interpreter that is registering the autostart (``sys.executable``)
    rather than an ``agenteye`` console script that may belong to a
    different interpreter without the tray dependencies installed. Combined with
    a ``WorkingDirectory`` of the repo root, this guarantees the deps match. For
    "app" mode the tray app runs in the foreground (ideal for launchd); for
    "server" mode we use the foreground ``_serve`` command so launchd manages a
    long-lived process.
    """
    base = [sys.executable, "-m", "src.session_dashboard"]
    if mode == "app":
        return [*base, "app", "--hidden", "--port", str(port)]
    return [*base, "_serve", "--port", str(port)]


def _write_macos_launch_agent(port: int, mode: str) -> str:
    """Write the LaunchAgent plist and return its path."""
    from plistlib import dump as plist_dump

    plist_path = _macos_plist_path()
    os.makedirs(os.path.dirname(plist_path), exist_ok=True)

    log_dir = os.path.expanduser("~/Library/Logs")
    os.makedirs(log_dir, exist_ok=True)

    plist = {
        "Label": MACOS_LAUNCH_AGENT_LABEL,
        "ProgramArguments": _get_autostart_program_args(port, mode),
        "RunAtLoad": True,
        # Interactive so the tray app gets access to the GUI/Aqua session.
        "ProcessType": "Interactive",
        # No KeepAlive: quitting from the tray should stay quit until next login.
        "StandardOutPath": os.path.join(log_dir, "agenteye.out.log"),
        "StandardErrorPath": os.path.join(log_dir, "agenteye.err.log"),
    }
    # Always set WorkingDirectory: the python -m invocation must run from the
    # repo root so the ``src`` package is importable.
    plist["WorkingDirectory"] = os.path.dirname(PKG_DIR)

    with open(plist_path, "wb") as f:
        plist_dump(plist, f)
    return plist_path


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    """Run a launchctl command, capturing output."""
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def _macos_autostart_enable(port: int, mode: str) -> None:
    """Register and load the macOS LaunchAgent."""
    plist_path = _write_macos_launch_agent(port, mode)
    uid = os.getuid()

    # Unload any previous instance first (ignore errors), then load the new one.
    _launchctl("bootout", f"gui/{uid}/{MACOS_LAUNCH_AGENT_LABEL}")
    result = _launchctl("bootstrap", f"gui/{uid}", plist_path)
    if result.returncode != 0:
        # Fall back to the legacy load command on older macOS versions.
        result = _launchctl("load", "-w", plist_path)

    mode_desc = "tray app" if mode == "app" else "background server"
    print(f"Autostart enabled — {mode_desc} will start on login (port {port}).")
    print(f"  LaunchAgent: {plist_path}")
    print(f"  Command:     {' '.join(_get_autostart_program_args(port, mode))}")
    if result.returncode != 0 and result.stderr.strip():
        print(f"  Note: launchctl reported: {result.stderr.strip()}")
    print("To remove: agenteye autostart-remove")


def _macos_autostart_remove() -> None:
    """Unload and delete the macOS LaunchAgent."""
    plist_path = _macos_plist_path()
    uid = os.getuid()

    _launchctl("bootout", f"gui/{uid}/{MACOS_LAUNCH_AGENT_LABEL}")
    _launchctl("unload", "-w", plist_path)  # legacy fallback, harmless if unused

    if os.path.exists(plist_path):
        os.remove(plist_path)
        print(f"Autostart removed — LaunchAgent deleted ({plist_path}).")
    else:
        print("Autostart is not currently configured (no LaunchAgent found).")


def _extract_port(cmd_str: str | None) -> int:
    """Extract --port from an autostart command string."""
    if not cmd_str:
        return DEFAULT_PORT
    m = re.search(r"--port\s+(\d+)", cmd_str)
    if not m:
        return DEFAULT_PORT
    try:
        return int(m.group(1))
    except ValueError:
        return DEFAULT_PORT


def _migrate_windows_autostart() -> None:
    """Migrate old Windows autostart registry value to the new value name."""
    if sys.platform != "win32":
        return
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE
    ) as key:
        try:
            old_cmd, _ = winreg.QueryValueEx(key, OLD_TASK_NAME)
        except FileNotFoundError:
            return

        old_port = _extract_port(old_cmd if isinstance(old_cmd, str) else None)
        try:
            winreg.DeleteValue(key, OLD_TASK_NAME)
        except FileNotFoundError:
            pass

        try:
            winreg.QueryValueEx(key, TASK_NAME)
        except FileNotFoundError:
            winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, _get_autostart_cmd_str(old_port))


def _migrate_macos_autostart() -> None:
    """Remove stale legacy macOS LaunchAgent plist/label if present."""
    if sys.platform != "darwin":
        return
    launch_agents = os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents")
    old_plist = os.path.join(launch_agents, f"{OLD_MACOS_LAUNCH_AGENT_LABEL}.plist")
    if not os.path.exists(old_plist):
        return
    uid = str(os.getuid())
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{OLD_MACOS_LAUNCH_AGENT_LABEL}"],
        check=False,
        capture_output=True,
    )
    subprocess.run(["launchctl", "unload", "-w", old_plist], check=False, capture_output=True)
    try:
        os.remove(old_plist)
    except OSError:
        pass


def _migrate_autostart() -> None:
    """Run safe, idempotent autostart migration steps during startup."""
    try:
        _migrate_windows_autostart()
    except Exception as e:
        print(f"Warning: Windows autostart migration failed: {e}")
    try:
        _migrate_macos_autostart()
    except Exception as e:
        print(f"Warning: macOS autostart migration failed: {e}")


def cmd_autostart(args):
    """Register the dashboard to start automatically at login."""
    port = args.port
    mode = getattr(args, "mode", "server")

    if sys.platform == "darwin":
        _macos_autostart_enable(port, mode)
        return

    if sys.platform != "win32":
        print("Error: autostart is only supported on Windows and macOS.")
        print("Linux support is planned for a future release.")
        sys.exit(1)

    import winreg

    cmd_str = _get_autostart_cmd_str(port, mode)

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, OLD_TASK_NAME)
            except FileNotFoundError:
                pass
            winreg.SetValueEx(key, TASK_NAME, 0, winreg.REG_SZ, cmd_str)
        mode_desc = "tray app" if mode == "app" else "background server"
        print(f"Autostart enabled — {mode_desc} will start on login (port {port}).")
        print(f"  Registry: HKCU\\{_RUN_KEY}\\{TASK_NAME}")
        print(f"  Command:  {cmd_str}")
        print("To remove: agenteye autostart-remove")
    except OSError as e:
        print(f"Failed to set registry key: {e}")
        sys.exit(1)


def cmd_app(args):
    """Run the dashboard as a system tray application."""
    from .tray_app import run_tray_app

    run_tray_app(
        port=args.port,
        log_level=getattr(args, "log_level", None),
        start_hidden=getattr(args, "hidden", False),
    )


def cmd_autostart_remove(_args):
    """Remove the dashboard autostart entry."""
    if sys.platform == "darwin":
        _macos_autostart_remove()
        return

    if sys.platform != "win32":
        print("Error: autostart is only supported on Windows and macOS.")
        print("Linux support is planned for a future release.")
        sys.exit(1)

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, TASK_NAME)
        print(f"Autostart removed — registry value '{TASK_NAME}' deleted.")
    except FileNotFoundError:
        print("Autostart is not currently configured (no registry entry found).")
    except OSError as e:
        print(f"Failed to remove registry entry: {e}")
        sys.exit(1)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agenteye",
        description="Agent Eye - monitor all your Copilot CLI sessions",
        epilog=(
            "Examples:\n"
            "  agenteye start                  Start in foreground\n"
            "  agenteye start --background     Start as background process\n"
            "  agenteye start -b --port 8080   Background on custom port\n"
            "  agenteye stop                   Stop the background server\n"
            "  agenteye status                 Check if server is running\n"
            "  agenteye upgrade                Upgrade to latest version\n"
            "  agenteye app                    Run as system tray app\n"
            "  agenteye autostart              Start on login (Windows/macOS)\n"
            "  agenteye autostart-remove       Remove login startup\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    start_p = sub.add_parser("start", help="Start the dashboard web server")
    start_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    start_p.add_argument(
        "--background", "-b", action="store_true", help="Run as a background process (detached)"
    )
    start_p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging verbosity (default: INFO, or value from config)",
    )

    stop_p = sub.add_parser("stop", help="Stop the background dashboard server")
    stop_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port the dashboard is running on (default: {DEFAULT_PORT})",
    )
    status_p = sub.add_parser("status", help="Check if the dashboard server is running")
    status_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to check (default: {DEFAULT_PORT})",
    )
    upgrade_p = sub.add_parser("upgrade", help="Upgrade to the latest version from PyPI")
    upgrade_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port the dashboard is running on (default: {DEFAULT_PORT})",
    )

    autostart_p = sub.add_parser(
        "autostart", help="Start dashboard automatically at login (Windows/macOS)"
    )
    autostart_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port for the autostarted dashboard (default: {DEFAULT_PORT})",
    )
    autostart_p.add_argument(
        "--mode",
        choices=["server", "app"],
        default="server",
        help="Mode to start in: 'server' (headless background) or 'app' (tray app with window)",
    )
    sub.add_parser("autostart-remove", help="Remove the login autostart task")

    app_p = sub.add_parser("app", help="Run as a system tray application with native window")
    app_p.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT})",
    )
    app_p.add_argument(
        "--hidden",
        action="store_true",
        help="Start with window hidden (minimized to tray)",
    )
    app_p.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
        help="Logging verbosity (default: INFO)",
    )

    serve_p = sub.add_parser("_serve", help=argparse.SUPPRESS)
    serve_p.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve_p.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default=None)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    {
        "start": cmd_start,
        "_serve": cmd_serve,
        "stop": cmd_stop,
        "status": cmd_status,
        "upgrade": cmd_upgrade,
        "autostart": cmd_autostart,
        "autostart-remove": cmd_autostart_remove,
        "app": cmd_app,
    }[args.command](args)


if __name__ == "__main__":
    main()
