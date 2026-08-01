"""Tests for the lightweight macOS .app bundle helpers."""

import argparse
import plistlib
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.__version__ import __version__
from src.macos_app import (
    APP_BUNDLE_IDENTIFIER,
    APP_BUNDLE_NAME,
    APP_EXECUTABLE_NAME,
    APP_GENERATED_KEY,
    APP_GENERATED_VALUE,
    APP_ICON_NAME,
    install_app_bundle,
    uninstall_app_bundle,
)
from src.session_dashboard import cmd_install_app, cmd_uninstall_app


def _fake_write_icns(icon_path: Path) -> None:
    icon_path.write_bytes(b"icns")


class TestInstallAppBundle:
    @patch("src.macos_app._refresh_spotlight")
    @patch("src.macos_app._write_icns", side_effect=_fake_write_icns)
    def test_creates_bundle_with_expected_plist_and_launcher(
        self, _write_icns, mock_refresh, tmp_path
    ):
        apps_dir = tmp_path / "Applications"
        python_executable = "/tmp/Agent Eye Python/bin/python3"

        bundle_path = install_app_bundle(
            applications_dir=apps_dir, python_executable=python_executable
        )

        assert bundle_path == apps_dir / APP_BUNDLE_NAME
        assert bundle_path.exists()

        plist_path = bundle_path / "Contents" / "Info.plist"
        with plist_path.open("rb") as handle:
            info = plistlib.load(handle)
        assert info["CFBundleName"] == "Agent Eye"
        assert info["CFBundleDisplayName"] == "Agent Eye"
        assert info["CFBundleIdentifier"] == APP_BUNDLE_IDENTIFIER
        assert info["CFBundleExecutable"] == APP_EXECUTABLE_NAME
        assert info["CFBundleIconFile"] == APP_ICON_NAME
        assert info["CFBundlePackageType"] == "APPL"
        assert info["CFBundleShortVersionString"] == __version__
        assert info["CFBundleVersion"] == __version__
        assert info[APP_GENERATED_KEY] == APP_GENERATED_VALUE
        assert info["AgentEyePythonExecutable"] == python_executable

        launcher_path = bundle_path / "Contents" / "MacOS" / APP_EXECUTABLE_NAME
        launcher = launcher_path.read_text(encoding="utf-8")
        assert launcher.startswith("#!/bin/sh\n")
        assert " -m src.session_dashboard app --foreground " in launcher
        assert "'/tmp/Agent Eye Python/bin/python3'" in launcher
        assert launcher_path.stat().st_mode & stat.S_IXUSR

        icon_path = bundle_path / "Contents" / "Resources" / APP_ICON_NAME
        assert icon_path.read_bytes() == b"icns"
        mock_refresh.assert_called_once_with(bundle_path)

    @patch("src.macos_app._refresh_spotlight")
    @patch("src.macos_app._write_icns", side_effect=_fake_write_icns)
    def test_reinstalls_over_existing_generated_bundle(self, _write_icns, _refresh, tmp_path):
        apps_dir = tmp_path / "Applications"
        bundle_path = install_app_bundle(
            applications_dir=apps_dir, python_executable="/tmp/python-a"
        )
        stale_file = bundle_path / "stale.txt"
        stale_file.write_text("old", encoding="utf-8")

        install_app_bundle(applications_dir=apps_dir, python_executable="/tmp/python-b")

        launcher = (bundle_path / "Contents" / "MacOS" / APP_EXECUTABLE_NAME).read_text(
            encoding="utf-8"
        )
        assert "/tmp/python-b" in launcher
        assert not stale_file.exists()

    @patch("src.macos_app._refresh_spotlight")
    @patch("src.macos_app._write_icns", side_effect=_fake_write_icns)
    def test_refuses_to_overwrite_unrecognized_bundle(self, _write_icns, _refresh, tmp_path):
        apps_dir = tmp_path / "Applications"
        bundle_path = apps_dir / APP_BUNDLE_NAME
        plist_path = bundle_path / "Contents" / "Info.plist"
        plist_path.parent.mkdir(parents=True)
        with plist_path.open("wb") as handle:
            plistlib.dump({"CFBundleIdentifier": "com.example.other"}, handle)

        with pytest.raises(RuntimeError, match="Refusing to overwrite existing app"):
            install_app_bundle(applications_dir=apps_dir, python_executable="/tmp/python")

        assert plist_path.exists()


class TestUninstallAppBundle:
    @patch("src.macos_app._refresh_spotlight")
    @patch("src.macos_app._write_icns", side_effect=_fake_write_icns)
    def test_removes_generated_bundle_and_is_idempotent(self, _write_icns, _refresh, tmp_path):
        apps_dir = tmp_path / "Applications"
        bundle_path = install_app_bundle(applications_dir=apps_dir, python_executable="/tmp/python")

        removed_path = uninstall_app_bundle(applications_dir=apps_dir)
        assert removed_path == bundle_path
        assert not bundle_path.exists()
        assert uninstall_app_bundle(applications_dir=apps_dir) is None

    def test_refuses_to_remove_unrecognized_bundle(self, tmp_path):
        apps_dir = tmp_path / "Applications"
        bundle_path = apps_dir / APP_BUNDLE_NAME
        plist_path = bundle_path / "Contents" / "Info.plist"
        plist_path.parent.mkdir(parents=True)
        with plist_path.open("wb") as handle:
            plistlib.dump({"CFBundleIdentifier": "com.example.other"}, handle)

        with pytest.raises(RuntimeError, match="Refusing to remove existing app"):
            uninstall_app_bundle(applications_dir=apps_dir)


class TestInstallAppCommands:
    def test_install_app_errors_on_unsupported_platform(self):
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            with pytest.raises(SystemExit):
                cmd_install_app(argparse.Namespace())

    def test_uninstall_app_errors_on_unsupported_platform(self):
        with patch("src.session_dashboard.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.exit = MagicMock(side_effect=SystemExit(1))
            with pytest.raises(SystemExit):
                cmd_uninstall_app(argparse.Namespace())
