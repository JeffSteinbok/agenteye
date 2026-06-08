"""
Desktop app installer for Copilot Dashboard.

Downloads the pre-built Electron desktop app from GitHub Releases
and installs it to the platform-appropriate location.
"""

from __future__ import annotations

import io
import json
import os
import platform
import shutil
import sys
import tempfile
import urllib.request
import zipfile

from .__version__ import __repository__, __version__

# GitHub API URL for releases
_GITHUB_API = "https://api.github.com/repos"
_REPO_OWNER = "JeffSteinbok"
_REPO_NAME = "ghcpCliDashboard"

# Platform-specific asset name patterns
_ASSET_PATTERNS: dict[str, dict[str, str]] = {
    "darwin": {
        "arm64": "copilot-dashboard-mac-arm64.zip",
        "x86_64": "copilot-dashboard-mac-x64.zip",
    },
    "win32": {
        "AMD64": "copilot-dashboard-win-x64.zip",
    },
    "linux": {
        "x86_64": "copilot-dashboard-linux-x64.zip",
    },
}

# Default install locations
_INSTALL_DIRS: dict[str, str] = {
    "darwin": "/Applications",
    "win32": os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Copilot Dashboard"),
    "linux": os.path.expanduser("~/.local/share/applications"),
}

_APP_NAME = "Copilot Dashboard"
_VERSION_FILE = ".copilot-dashboard-version"


def _get_install_dir() -> str:
    """Return the platform-appropriate install directory."""
    return _INSTALL_DIRS.get(sys.platform, "")


def _get_asset_name() -> str | None:
    """Return the expected asset filename for the current platform."""
    plat = _ASSET_PATTERNS.get(sys.platform, {})
    machine = platform.machine()
    return plat.get(machine)


def _get_installed_version(install_dir: str) -> str | None:
    """Read the version of the currently installed desktop app."""
    version_file = os.path.join(install_dir, _VERSION_FILE)
    if os.path.exists(version_file):
        try:
            with open(version_file, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            pass
    return None


def _write_installed_version(install_dir: str, version: str) -> None:
    """Record the version of the installed desktop app."""
    version_file = os.path.join(install_dir, _VERSION_FILE)
    try:
        with open(version_file, "w", encoding="utf-8") as f:
            f.write(version)
    except OSError:
        pass


def _find_release_asset(version: str, asset_name: str) -> str | None:
    """Find the download URL for a specific asset in a GitHub release.

    Tries the tag matching the pip version first (v0.9.2), then falls
    back to the latest release.
    """
    headers = {"Accept": "application/vnd.github+json"}

    # Try exact version tag first
    for tag in [f"v{version}", version]:
        url = f"{_GITHUB_API}/{_REPO_OWNER}/{_REPO_NAME}/releases/tags/{tag}"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                release = json.loads(resp.read())
                for asset in release.get("assets", []):
                    if asset["name"] == asset_name:
                        return str(asset["browser_download_url"])
        except Exception:
            continue

    # Fall back to latest release
    url = f"{_GITHUB_API}/{_REPO_OWNER}/{_REPO_NAME}/releases/latest"
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            release = json.loads(resp.read())
            for asset in release.get("assets", []):
                if asset["name"] == asset_name:
                    return str(asset["browser_download_url"])
    except Exception:
        pass

    return None


def _download_and_extract(url: str, dest_dir: str) -> None:
    """Download a zip from url and extract to dest_dir."""
    print(f"  Downloading from {url}...")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    size_mb = len(data) / (1024 * 1024)
    print(f"  Downloaded {size_mb:.1f} MB")

    print(f"  Extracting to {dest_dir}...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(dest_dir)


def install_app(_args: object = None) -> None:
    """Download and install the Copilot Dashboard desktop app."""
    install_dir = _get_install_dir()
    if not install_dir:
        print(f"Error: Desktop app is not supported on {sys.platform}")
        sys.exit(1)

    asset_name = _get_asset_name()
    if not asset_name:
        machine = platform.machine()
        print(f"Error: No desktop app available for {sys.platform}/{machine}")
        sys.exit(1)

    # Check if already installed at the current version
    installed = _get_installed_version(install_dir)
    if installed == __version__:
        print(f"Copilot Dashboard desktop app v{__version__} is already installed.")
        print(f"  Location: {install_dir}")
        if sys.platform == "darwin":
            app_path = os.path.join(install_dir, f"{_APP_NAME}.app")
            if os.path.exists(app_path):
                print(f"  Launch: open '{app_path}'")
        return

    if installed:
        print(f"Upgrading desktop app: v{installed} → v{__version__}")
    else:
        print(f"Installing Copilot Dashboard desktop app v{__version__}...")

    # Find the download URL
    print("  Looking for release assets on GitHub...")
    download_url = _find_release_asset(__version__, asset_name)
    if not download_url:
        print(f"\nError: Could not find {asset_name} in GitHub releases.")
        print(f"  Checked: {__repository__}/releases")
        print(
            "\n  The desktop app may not be available for this version yet."
            "\n  You can still use the dashboard in your browser:"
            "\n    copilot-dashboard start"
        )
        sys.exit(1)

    # Download and extract
    with tempfile.TemporaryDirectory() as tmp:
        _download_and_extract(download_url, tmp)

        if sys.platform == "darwin":
            # Move .app to /Applications
            src_app = None
            for item in os.listdir(tmp):
                if item.endswith(".app"):
                    src_app = os.path.join(tmp, item)
                    break

            if not src_app:
                print("Error: No .app found in the downloaded archive.")
                sys.exit(1)

            dest_app = os.path.join(install_dir, f"{_APP_NAME}.app")
            if os.path.exists(dest_app):
                print(f"  Removing old version at {dest_app}...")
                shutil.rmtree(dest_app)

            shutil.move(src_app, dest_app)
            # Remove quarantine flag (locally installed, not from internet)
            os.system(f'xattr -rd com.apple.quarantine "{dest_app}" 2>/dev/null')

        elif sys.platform == "win32":
            os.makedirs(install_dir, exist_ok=True)
            for item in os.listdir(tmp):
                src = os.path.join(tmp, item)
                dst = os.path.join(install_dir, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                shutil.move(src, dst)

    _write_installed_version(install_dir, __version__)

    print("\n✅ Copilot Dashboard desktop app installed!")
    print(f"   Location: {install_dir}")
    if sys.platform == "darwin":
        print(f"   Launch: open '/Applications/{_APP_NAME}.app'")
        print("   Tip: Drag it to your Dock to pin it!")


def uninstall_app(_args: object = None) -> None:
    """Remove the Copilot Dashboard desktop app."""
    install_dir = _get_install_dir()
    if not install_dir:
        print(f"Desktop app is not supported on {sys.platform}")
        return

    if sys.platform == "darwin":
        app_path = os.path.join(install_dir, f"{_APP_NAME}.app")
        if os.path.exists(app_path):
            shutil.rmtree(app_path)
            print(f"Removed {app_path}")
        else:
            print("Desktop app is not installed.")
            return
    elif sys.platform == "win32":
        if os.path.exists(install_dir):
            shutil.rmtree(install_dir)
            print(f"Removed {install_dir}")
        else:
            print("Desktop app is not installed.")
            return

    # Remove version file
    version_file = os.path.join(install_dir, _VERSION_FILE)
    if os.path.exists(version_file):
        os.remove(version_file)

    print("Desktop app uninstalled.")
