"""
Centralised logging configuration for the Agent Eye.

Provides a single ``setup_logging()`` call that configures the root
``src`` logger with a :class:`~logging.handlers.RotatingFileHandler`
so log output is persisted to disk and automatically rotated.
"""

from __future__ import annotations

import logging
import logging.handlers
import os

from .constants import (
    DASHBOARD_LOG_FILE,
    DEFAULT_LOG_LEVEL,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
)

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Module-level state so we can query/change at runtime.
_current_level: str = DEFAULT_LOG_LEVEL
_current_log_file: str = DASHBOARD_LOG_FILE


_VALID_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


def setup_logging(
    level: str | None = None,
    log_file: str | None = None,
) -> None:
    """Configure the ``src`` logger hierarchy with a rotating file handler.

    Parameters
    ----------
    level:
        Logging level name (DEBUG, INFO, WARNING, ERROR).  Falls back to
        the value in ``dashboard-config.json``, then :data:`DEFAULT_LOG_LEVEL`.
    log_file:
        Path for the log file.  Defaults to :data:`DASHBOARD_LOG_FILE`
        (``~/.copilot/dashboard.log``).
    """
    global _current_level, _current_log_file

    resolved_level = (level or _resolve_config_level() or DEFAULT_LOG_LEVEL).upper()
    if resolved_level not in _VALID_LEVELS:
        resolved_level = DEFAULT_LOG_LEVEL
    resolved_file = log_file or DASHBOARD_LOG_FILE

    _current_level = resolved_level
    _current_log_file = resolved_file

    # Ensure the directory exists (e.g. first run before ~/.copilot exists).
    os.makedirs(os.path.dirname(resolved_file), exist_ok=True)

    root = logging.getLogger("src")
    root.setLevel(resolved_level)

    # Avoid duplicate handlers on repeated calls (e.g. tests).
    if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers):
        handler = logging.handlers.RotatingFileHandler(
            resolved_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
        root.addHandler(handler)

    # Also attach a concise stderr handler so foreground runs still see output.
    if not any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
        for h in root.handlers
    ):
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(console)


def set_log_level(level: str) -> None:
    """Change the logging level at runtime."""
    global _current_level
    new_level = level.upper()
    if new_level not in _VALID_LEVELS:
        return
    _current_level = new_level
    logging.getLogger("src").setLevel(_current_level)
    # Update the file handler level too (console stays at WARNING).
    for h in logging.getLogger("src").handlers:
        if isinstance(h, logging.handlers.RotatingFileHandler):
            h.setLevel(_current_level)


def get_log_level() -> str:
    """Return the current effective log level name."""
    return _current_level


def get_log_file() -> str:
    """Return the path of the current log file."""
    return _current_log_file


def _resolve_config_level() -> str | None:
    """Read ``logging.level`` from dashboard-config.json, if present."""
    try:
        import json

        from .constants import DASHBOARD_CONFIG_PATH

        with open(DASHBOARD_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        level: str | None = cfg.get("logging", {}).get("level")
        return level
    except Exception:
        return None
