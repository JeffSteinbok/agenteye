"""Tests for sync.py — cross-machine session sync."""

import json
import time
from datetime import UTC, datetime
from unittest.mock import patch

from src.sync import (
    cleanup_stale_sessions,
    export_sessions,
    get_machine_name,
    read_remote_sessions,
    resolve_sync_folder,
    sync_config_from_shared,
    sync_config_to_shared,
)

MACHINE = "test-host"


# ── get_machine_name ─────────────────────────────────────────────────────────


class TestGetMachineName:
    def test_returns_non_empty_string(self):
        name = get_machine_name()
        assert isinstance(name, str)
        assert len(name) > 0


# ── resolve_sync_folder ─────────────────────────────────────────────────────


class TestResolveSyncFolder:
    def test_returns_none_when_sync_disabled(self, tmp_path):
        config = {"sync": {"enabled": False}}
        config_file = tmp_path / "dashboard-config.json"
        config_file.write_text(json.dumps(config))
        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)):
            result = resolve_sync_folder()
        assert result is None

    def test_returns_explicit_folder(self, tmp_path):
        sync_root = tmp_path / "my-sync"
        sync_root.mkdir()
        config = {"sync": {"folder": str(sync_root)}}
        config_file = tmp_path / "dashboard-config.json"
        config_file.write_text(json.dumps(config))
        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)):
            result = resolve_sync_folder()
        assert result is not None
        assert result == sync_root / "AgentEye"

    def test_returns_none_when_explicit_folder_missing(self, tmp_path):
        config = {"sync": {"folder": str(tmp_path / "no-such-dir")}}
        config_file = tmp_path / "dashboard-config.json"
        config_file.write_text(json.dumps(config))
        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)):
            result = resolve_sync_folder()
        assert result is None

    def test_returns_onedrive_commercial_when_env_set(self, tmp_path):
        onedrive = tmp_path / "OneDrive"
        onedrive.mkdir()
        config_file = tmp_path / "empty-config.json"
        # no sync config → falls through to env vars
        config_file.write_text("{}")
        env = {"OneDriveCommercial": str(onedrive)}
        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", env, clear=False),
        ):
            # Ensure Path.is_dir works on our temp dir
            result = resolve_sync_folder()
        assert result is not None
        assert result == onedrive / "AgentEye"

    def test_falls_back_to_documents(self, tmp_path):
        docs = tmp_path / "Documents"
        docs.mkdir()
        config_file = tmp_path / "empty-config.json"
        config_file.write_text("{}")
        env = {"OneDriveCommercial": "", "OneDriveConsumer": ""}
        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", env, clear=False),
            patch("src.sync.Path.home", return_value=tmp_path),
        ):
            result = resolve_sync_folder()
        assert result is not None
        assert result == docs / "AgentEye"

    def test_detects_macos_cloudstorage_onedrive_prefer_commercial(self, tmp_path):
        cloud_storage = tmp_path / "Library" / "CloudStorage"
        cloud_storage.mkdir(parents=True)
        personal = cloud_storage / "OneDrive-Personal"
        personal.mkdir()
        commercial = cloud_storage / "OneDrive-Microsoft"
        commercial.mkdir()

        config_file = tmp_path / "empty-config.json"
        config_file.write_text("{}")

        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", {}, clear=False),
            patch("src.sync.Path.home", return_value=tmp_path),
        ):
            result = resolve_sync_folder()

        assert result is not None
        assert result == commercial / "AgentEye"

    def test_detects_macos_cloudstorage_personal_when_only_personal(self, tmp_path):
        cloud_storage = tmp_path / "Library" / "CloudStorage"
        cloud_storage.mkdir(parents=True)
        personal = cloud_storage / "OneDrive-Personal"
        personal.mkdir()

        config_file = tmp_path / "empty-config.json"
        config_file.write_text("{}")

        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", {}, clear=False),
            patch("src.sync.Path.home", return_value=tmp_path),
        ):
            result = resolve_sync_folder()

        assert result is not None
        assert result == personal / "AgentEye"

    def test_detects_legacy_onedrive_when_cloudstorage_missing(self, tmp_path):
        legacy_personal = tmp_path / "OneDrive"
        legacy_personal.mkdir()
        legacy_commercial = tmp_path / "OneDrive - Microsoft"
        legacy_commercial.mkdir()

        config_file = tmp_path / "empty-config.json"
        config_file.write_text("{}")

        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", {}, clear=False),
            patch("src.sync.Path.home", return_value=tmp_path),
        ):
            result = resolve_sync_folder()

        assert result is not None
        assert result == legacy_commercial / "AgentEye"

    def test_returns_none_when_no_suitable_folder(self, tmp_path):
        # No Documents folder, no OneDrive, no config
        config_file = tmp_path / "empty-config.json"
        config_file.write_text("{}")
        env = {"OneDriveCommercial": "", "OneDriveConsumer": ""}
        fake_home = tmp_path / "fakehome"
        fake_home.mkdir()
        with (
            patch("src.sync.DASHBOARD_CONFIG_PATH", str(config_file)),
            patch.dict("os.environ", env, clear=False),
            patch("src.sync.Path.home", return_value=fake_home),
        ):
            result = resolve_sync_folder()
        assert result is None


# ── export_sessions ──────────────────────────────────────────────────────────


class TestExportSessions:
    def test_creates_machine_directory_structure(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        with patch("src.sync.get_machine_name", return_value=MACHINE):
            export_sessions([], sync_folder)
        assert (sync_folder / MACHINE / "sessions").is_dir()
        assert (sync_folder / MACHINE / "machine.json").is_file()

    def test_writes_session_json_files(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        sessions = [
            {"id": "sess-1", "cwd": "/project", "summary": "test"},
            {"id": "sess-2", "cwd": "/other", "summary": "other"},
        ]
        with patch("src.sync.get_machine_name", return_value=MACHINE):
            export_sessions(sessions, sync_folder)

        sessions_dir = sync_folder / MACHINE / "sessions"
        assert (sessions_dir / "sess-1.json").is_file()
        assert (sessions_dir / "sess-2.json").is_file()

        data = json.loads((sessions_dir / "sess-1.json").read_text())
        assert data["id"] == "sess-1"
        assert data["machine_name"] == MACHINE

    def test_writes_machine_json_with_metadata(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        sessions = [{"id": "s1", "cwd": "/a"}]
        with patch("src.sync.get_machine_name", return_value=MACHINE):
            export_sessions(sessions, sync_folder)

        info = json.loads((sync_folder / MACHINE / "machine.json").read_text())
        assert info["hostname"] == MACHINE
        assert info["active_session_count"] == 1

    def test_skips_sessions_with_empty_id(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        sessions = [
            {"id": "", "cwd": "/a"},
            {"id": "valid", "cwd": "/b"},
        ]
        with patch("src.sync.get_machine_name", return_value=MACHINE):
            export_sessions(sessions, sync_folder)

        sessions_dir = sync_folder / MACHINE / "sessions"
        files = list(sessions_dir.glob("*.json"))
        assert len(files) == 1
        assert files[0].name == "valid.json"

    def test_cleans_up_stale_session_files(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sessions_dir = sync_folder / MACHINE / "sessions"
        sessions_dir.mkdir(parents=True)
        # Pre-existing stale file
        (sessions_dir / "old-session.json").write_text("{}")

        sessions = [{"id": "new-session", "cwd": "/a"}]
        with patch("src.sync.get_machine_name", return_value=MACHINE):
            export_sessions(sessions, sync_folder)

        assert not (sessions_dir / "old-session.json").exists()
        assert (sessions_dir / "new-session.json").exists()


# ── cleanup_stale_sessions ───────────────────────────────────────────────────


class TestCleanupStaleSessions:
    def test_removes_files_not_in_active_ids(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "keep.json").write_text("{}")
        (sessions_dir / "remove.json").write_text("{}")

        cleanup_stale_sessions({"keep"}, sessions_dir)

        assert (sessions_dir / "keep.json").exists()
        assert not (sessions_dir / "remove.json").exists()

    def test_keeps_files_in_active_ids(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        (sessions_dir / "a.json").write_text("{}")
        (sessions_dir / "b.json").write_text("{}")

        cleanup_stale_sessions({"a", "b"}, sessions_dir)

        assert (sessions_dir / "a.json").exists()
        assert (sessions_dir / "b.json").exists()

    def test_noop_when_dir_missing(self, tmp_path):
        missing = tmp_path / "nonexistent"
        # Should not raise
        cleanup_stale_sessions(set(), missing)


# ── read_remote_sessions ─────────────────────────────────────────────────────


class TestReadRemoteSessions:
    def test_returns_empty_when_sync_folder_missing(self, tmp_path):
        missing = tmp_path / "nonexistent"
        result = read_remote_sessions(missing)
        assert result == []

    def test_skips_local_machine(self, tmp_path):
        sync_folder = tmp_path / "sync"
        local_dir = sync_folder / MACHINE
        sessions_dir = local_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "s1.json").write_text(json.dumps({"id": "s1"}))
        machine_info = {"last_sync": datetime.now(UTC).isoformat()}
        (local_dir / "machine.json").write_text(json.dumps(machine_info))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            result = read_remote_sessions(sync_folder)
        assert result == []

    def test_reads_sessions_from_other_machines(self, tmp_path):
        sync_folder = tmp_path / "sync"
        remote_dir = sync_folder / "remote-host"
        sessions_dir = remote_dir / "sessions"
        sessions_dir.mkdir(parents=True)

        session_data = {"id": "r1", "cwd": "/remote"}
        (sessions_dir / "r1.json").write_text(json.dumps(session_data))
        machine_info = {"last_sync": datetime.now(UTC).isoformat()}
        (remote_dir / "machine.json").write_text(json.dumps(machine_info))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            result = read_remote_sessions(sync_folder)

        assert len(result) == 1
        assert result[0]["id"] == "r1"
        assert result[0]["machine_name"] == "remote-host"
        assert result[0]["is_running"] is True

    def test_skips_stale_machines(self, tmp_path):
        sync_folder = tmp_path / "sync"
        remote_dir = sync_folder / "stale-host"
        sessions_dir = remote_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "s1.json").write_text(json.dumps({"id": "s1"}))

        # Set last_sync far in the past (beyond SYNC_STALE_THRESHOLD)
        old_time = datetime.fromtimestamp(time.time() - 99999, tz=UTC).isoformat()
        (remote_dir / "machine.json").write_text(json.dumps({"last_sync": old_time}))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            result = read_remote_sessions(sync_folder)

        assert result == []
        # Stale dir should have been removed
        assert not remote_dir.exists()

    def test_removes_stale_machine_directories(self, tmp_path):
        sync_folder = tmp_path / "sync"
        stale_dir = sync_folder / "old-machine"
        stale_dir.mkdir(parents=True)

        old_time = datetime.fromtimestamp(time.time() - 99999, tz=UTC).isoformat()
        (stale_dir / "machine.json").write_text(json.dumps({"last_sync": old_time}))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            read_remote_sessions(sync_folder)

        assert not stale_dir.exists()

    def test_skips_machines_without_machine_json(self, tmp_path):
        sync_folder = tmp_path / "sync"
        remote_dir = sync_folder / "no-machine-json"
        sessions_dir = remote_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        (sessions_dir / "s1.json").write_text(json.dumps({"id": "s1"}))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            result = read_remote_sessions(sync_folder)
        assert result == []

    def test_sets_machine_name_and_is_running(self, tmp_path):
        sync_folder = tmp_path / "sync"
        remote_dir = sync_folder / "work-laptop"
        sessions_dir = remote_dir / "sessions"
        sessions_dir.mkdir(parents=True)

        (sessions_dir / "abc.json").write_text(json.dumps({"id": "abc"}))
        machine_info = {"last_sync": datetime.now(UTC).isoformat()}
        (remote_dir / "machine.json").write_text(json.dumps(machine_info))

        with patch("src.sync.get_machine_name", return_value=MACHINE):
            result = read_remote_sessions(sync_folder)

        assert len(result) == 1
        assert result[0]["machine_name"] == "work-laptop"
        assert result[0]["is_running"] is True


# ── sync_config_to_shared ───────────────────────────────────────────────────


class TestSyncConfigToShared:
    def test_copies_config_to_shared_folder(self, tmp_path):
        local_config = tmp_path / "local-config.json"
        local_config.write_text(json.dumps({"theme": "dark"}))

        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(local_config)):
            sync_config_to_shared(sync_folder)

        shared = sync_folder / "config" / "dashboard-config.json"
        assert shared.is_file()
        assert json.loads(shared.read_text()) == {"theme": "dark"}

    def test_noop_when_local_config_missing(self, tmp_path):
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(tmp_path / "missing.json")):
            sync_config_to_shared(sync_folder)

        assert not (sync_folder / "config").exists()


# ── sync_config_from_shared ─────────────────────────────────────────────────


class TestSyncConfigFromShared:
    def test_imports_when_shared_is_newer(self, tmp_path):
        local_config = tmp_path / "local-config.json"
        local_config.write_text(json.dumps({"old": True}))

        shared_dir = tmp_path / "sync" / "config"
        shared_dir.mkdir(parents=True)
        shared_config = shared_dir / "dashboard-config.json"
        shared_config.write_text(json.dumps({"new": True}))

        # Make shared file newer
        import os

        local_mtime = os.path.getmtime(local_config)
        os.utime(shared_config, (local_mtime + 100, local_mtime + 100))

        sync_folder = tmp_path / "sync"
        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(local_config)):
            sync_config_from_shared(sync_folder)

        assert json.loads(local_config.read_text()) == {"new": True}

    def test_does_not_overwrite_when_local_is_newer(self, tmp_path):
        local_config = tmp_path / "local-config.json"
        local_config.write_text(json.dumps({"local": True}))

        shared_dir = tmp_path / "sync" / "config"
        shared_dir.mkdir(parents=True)
        shared_config = shared_dir / "dashboard-config.json"
        shared_config.write_text(json.dumps({"shared": True}))

        # Make local file newer
        import os

        shared_mtime = os.path.getmtime(shared_config)
        os.utime(local_config, (shared_mtime + 100, shared_mtime + 100))

        sync_folder = tmp_path / "sync"
        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(local_config)):
            sync_config_from_shared(sync_folder)

        assert json.loads(local_config.read_text()) == {"local": True}

    def test_noop_when_shared_config_missing(self, tmp_path):
        local_config = tmp_path / "local-config.json"
        local_config.write_text(json.dumps({"keep": True}))

        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        with patch("src.sync.DASHBOARD_CONFIG_PATH", str(local_config)):
            sync_config_from_shared(sync_folder)

        assert json.loads(local_config.read_text()) == {"keep": True}
