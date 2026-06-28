"""Session grouping logic for the Agent Eye.

Derives a project/area group name from session metadata using a generic
algorithm. Supports optional user-defined custom group mappings via
~/.copilot/dashboard-config.json.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading

from .constants import DASHBOARD_CONFIG_PATH, DEFAULT_GROUP_NAME, KEYWORD_GROUPS, SKIP_DIRS

logger = logging.getLogger(__name__)

# Loaded once on first call, protected by lock
_custom_config: dict | None = None
_config_lock = threading.Lock()


def _load_config() -> dict:
    """Load optional user config from ~/.copilot/dashboard-config.json.

    Expected format:
    {
        "grouping": {
            "skip_dirs": ["myuser"],
            "mappings": {
                "keyword_or_path": "Group Name",
                "myrepo": "My Project"
            }
        }
    }
    """
    global _custom_config
    with _config_lock:
        if _custom_config is not None:
            return _custom_config
        _custom_config = {}
        if os.path.exists(DASHBOARD_CONFIG_PATH):
            try:
                with open(DASHBOARD_CONFIG_PATH, encoding="utf-8") as f:
                    _custom_config = json.load(f)
            except Exception as e:
                logger.warning("Failed to load %s: %s", DASHBOARD_CONFIG_PATH, e)
        return _custom_config


def get_group_name(session: dict) -> str:
    """Derive a project/area group name from session metadata.

    Strategy (in order):
    1. Check user-defined custom mappings
    2. Use repository field if available (owner/repo → repo)
    3. Extract from CWD path (last meaningful segment)
    4. Content-based keyword matching as fallback
    """
    config = _load_config()
    grouping = config.get("grouping", {})
    custom_mappings: dict[str, str] = grouping.get("mappings", {})
    extra_skip: list[str] = grouping.get("skip_dirs", [])

    cwd = (session.get("cwd") or "").replace("\\", "/")
    repository = session.get("repository") or ""
    summary = (session.get("summary") or "").lower()
    first_msg = (session.get("first_msg") or "").lower()
    last_cp = (session.get("last_cp_overview") or "").lower()
    context = f"{summary} {first_msg} {last_cp} {cwd.lower()}"

    # --- 1. Custom mappings (user-defined keywords/paths → group names) ---
    for keyword, group_name in custom_mappings.items():
        if keyword.lower() in context:
            return group_name

    # --- 2. Repository-based grouping ---
    if repository:
        # "owner/repo" → "repo", or just use as-is
        repo_name = repository.split("/")[-1] if "/" in repository else repository
        if repo_name:
            return repo_name

    # --- 3. CWD-based: last meaningful directory segment ---
    if cwd:
        # If the CWD is the user's home directory, use a friendly label
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        if cwd.rstrip("/").lower() == home.lower():
            return "🏠 Home"

        skip = SKIP_DIRS | {d.lower() for d in extra_skip}
        parts = cwd.rstrip("/").split("/")
        # Filter out drive letters, common dirs, and user-configured skips
        meaningful = [p for p in parts if p.lower() not in skip and not re.match(r"^[a-zA-Z]:$", p)]
        if meaningful:
            return meaningful[-1]

    # --- 4. Content-based keyword matching (fallback) ---
    for keywords, group_name in KEYWORD_GROUPS:
        if any(kw in context for kw in keywords):
            return group_name

    return DEFAULT_GROUP_NAME
