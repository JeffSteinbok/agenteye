"""Tests for the logging_config module and logging-related API endpoints."""

import json
import logging
import logging.handlers
import os
from unittest.mock import patch

import pytest


# ── Unit tests: logging_config ──────────────────────────────────────────────


class TestSetupLogging:
    """Tests for setup_logging()."""

    def _cleanup_logger(self):
        """Remove all handlers from the 'src' logger to isolate tests."""
        root = logging.getLogger("src")
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def setup_method(self):
        self._cleanup_logger()

    def teardown_method(self):
        self._cleanup_logger()

    def test_creates_rotating_file_handler(self, tmp_path):
        from src.logging_config import setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", log_file=log_file)

        root = logging.getLogger("src")
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1
        assert file_handlers[0].baseFilename == os.path.abspath(log_file)

    def test_creates_log_directory(self, tmp_path):
        from src.logging_config import setup_logging

        log_file = str(tmp_path / "subdir" / "nested" / "test.log")
        setup_logging(level="DEBUG", log_file=log_file)

        assert os.path.isdir(os.path.dirname(log_file))

    def test_does_not_duplicate_handlers(self, tmp_path):
        from src.logging_config import setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", log_file=log_file)
        setup_logging(level="DEBUG", log_file=log_file)

        root = logging.getLogger("src")
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(file_handlers) == 1

    def test_default_level_is_info(self, tmp_path):
        from src.logging_config import get_log_level, setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        assert get_log_level() == "INFO"

    def test_explicit_level_overrides_default(self, tmp_path):
        from src.logging_config import get_log_level, setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="DEBUG", log_file=log_file)
        assert get_log_level() == "DEBUG"

    def test_invalid_level_falls_back_to_default(self, tmp_path):
        from src.logging_config import get_log_level, setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="TRACE", log_file=log_file)
        assert get_log_level() == "INFO"

    def test_level_from_config_file(self, tmp_path):
        from src.logging_config import setup_logging, get_log_level

        config = {"logging": {"level": "WARNING"}}
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)

        log_file = str(tmp_path / "test.log")
        with patch("src.constants.DASHBOARD_CONFIG_PATH", config_path):
            setup_logging(log_file=log_file)

        assert get_log_level() == "WARNING"

    def test_invalid_level_in_config_falls_back(self, tmp_path):
        from src.logging_config import setup_logging, get_log_level

        config = {"logging": {"level": "FATAL"}}
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)

        log_file = str(tmp_path / "test.log")
        with patch("src.constants.DASHBOARD_CONFIG_PATH", config_path):
            setup_logging(log_file=log_file)

        assert get_log_level() == "INFO"

    def test_writes_to_log_file(self, tmp_path):
        from src.logging_config import setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="DEBUG", log_file=log_file)

        logger = logging.getLogger("src.test_module")
        logger.info("test message")

        with open(log_file) as f:
            content = f.read()
        assert "test message" in content

    def test_console_handler_attached(self, tmp_path):
        from src.logging_config import setup_logging

        log_file = str(tmp_path / "test.log")
        setup_logging(level="INFO", log_file=log_file)

        root = logging.getLogger("src")
        console_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert len(console_handlers) == 1
        assert console_handlers[0].level == logging.WARNING


class TestSetLogLevel:
    """Tests for set_log_level()."""

    def setup_method(self):
        root = logging.getLogger("src")
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def teardown_method(self):
        root = logging.getLogger("src")
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def test_changes_level(self, tmp_path):
        from src.logging_config import get_log_level, set_log_level, setup_logging

        setup_logging(level="INFO", log_file=str(tmp_path / "test.log"))
        set_log_level("DEBUG")
        assert get_log_level() == "DEBUG"
        assert logging.getLogger("src").level == logging.DEBUG

    def test_case_insensitive(self, tmp_path):
        from src.logging_config import get_log_level, set_log_level, setup_logging

        setup_logging(level="INFO", log_file=str(tmp_path / "test.log"))
        set_log_level("warning")
        assert get_log_level() == "WARNING"

    def test_invalid_level_ignored(self, tmp_path):
        from src.logging_config import get_log_level, set_log_level, setup_logging

        setup_logging(level="INFO", log_file=str(tmp_path / "test.log"))
        set_log_level("BANANA")
        assert get_log_level() == "INFO"


class TestGetters:
    """Tests for get_log_level() and get_log_file()."""

    def setup_method(self):
        root = logging.getLogger("src")
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def teardown_method(self):
        root = logging.getLogger("src")
        for h in root.handlers[:]:
            root.removeHandler(h)
            h.close()

    def test_get_log_file_returns_configured_path(self, tmp_path):
        from src.logging_config import get_log_file, setup_logging

        log_file = str(tmp_path / "custom.log")
        setup_logging(level="INFO", log_file=log_file)
        assert get_log_file() == log_file


# ── API tests: server-info includes log fields ─────────────────────────────


class TestServerInfoLogging:
    def test_server_info_includes_log_fields(self, client):
        resp = client.get("/api/server-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "log_file" in data
        assert "log_level" in data
        assert data["log_level"] in ("DEBUG", "INFO", "WARNING", "ERROR")


# ── API tests: settings log_level ───────────────────────────────────────────


class TestSettingsLogLevel:
    def test_get_settings_includes_log_level(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "log_level" in data
        assert data["log_level"] in ("DEBUG", "INFO", "WARNING", "ERROR")

    def test_put_settings_changes_log_level(self, client, tmp_path):
        config_path = str(tmp_path / "config.json")
        with open(config_path, "w") as f:
            json.dump({}, f)

        with (
            patch("src.dashboard_api._read_dashboard_config", return_value={}),
            patch("src.dashboard_api._write_dashboard_config") as mock_write,
        ):
            resp = client.put("/api/settings", json={"log_level": "DEBUG"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["log_level"] == "DEBUG"

        # Verify config was written with logging.level
        written_cfg = mock_write.call_args[0][0]
        assert written_cfg["logging"]["level"] == "DEBUG"

    def test_put_settings_rejects_invalid_log_level(self, client):
        with (
            patch("src.dashboard_api._read_dashboard_config", return_value={}),
            patch("src.dashboard_api._write_dashboard_config"),
        ):
            resp = client.put("/api/settings", json={"log_level": "BANANA"})

        assert resp.status_code == 200
        # Level should NOT be "BANANA"
        assert resp.json()["log_level"] != "BANANA"


# ── Constants tests ─────────────────────────────────────────────────────────


class TestLoggingConstants:
    def test_log_file_path_uses_platformdirs(self):
        from src.constants import DASHBOARD_LOG_DIR, DASHBOARD_LOG_FILE

        assert "agenteye" in DASHBOARD_LOG_DIR
        assert DASHBOARD_LOG_FILE.endswith("dashboard.log")
        assert DASHBOARD_LOG_FILE.startswith(DASHBOARD_LOG_DIR)

    def test_rotation_defaults(self):
        from src.constants import DEFAULT_LOG_LEVEL, LOG_BACKUP_COUNT, LOG_MAX_BYTES

        assert LOG_MAX_BYTES == 5 * 1024 * 1024
        assert LOG_BACKUP_COUNT == 3
        assert DEFAULT_LOG_LEVEL == "INFO"
