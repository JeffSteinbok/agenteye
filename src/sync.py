"""
Cross-machine session sync via cloud-synced folders (OneDrive / Google Drive).

Each machine periodically exports its active sessions as JSON files into a
shared folder.  Other machines read those files to display remote sessions
in a dedicated dashboard section.

Folder layout::

    {sync_root}/AgentEye/
        {hostname}/
            machine.json
            sessions/
                {session-id}.json
        config/
            dashboard-config.json
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import time
from datetime import UTC, datetime
from pathlib import Path

from .constants import (
    DASHBOARD_CONFIG_PATH,
    SYNC_FOLDER_NAME,
    SYNC_STALE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# ── Machine identity ─────────────────────────────────────────────────────────


def get_machine_name() -> str:
    """Return the local machine's hostname (used as the per-machine subfolder)."""
    return socket.gethostname()


# ── Sync folder discovery ────────────────────────────────────────────────────


def _read_sync_config() -> dict[str, object]:
    """Read the ``sync`` section from dashboard-config.json, if present."""
    if not os.path.exists(DASHBOARD_CONFIG_PATH):
        return {}
    try:
        with open(DASHBOARD_CONFIG_PATH, encoding="utf-8") as f:
            result: dict[str, object] = json.load(f).get("sync", {})
            return result
    except Exception:
        return {}


def _find_onedrive_folder() -> Path | None:
    """Auto-discover OneDrive roots across supported platform layouts."""
    home = Path.home()

    # macOS modern layout: ~/Library/CloudStorage/OneDrive-*
    cloud_storage = home / "Library" / "CloudStorage"
    if cloud_storage.is_dir():
        commercial = sorted(
            p
            for p in cloud_storage.glob("OneDrive-*")
            if p.is_dir() and p.name.lower() != "onedrive-personal"
        )
        if commercial:
            return commercial[0]

        personal = cloud_storage / "OneDrive-Personal"
        if personal.is_dir():
            return personal

    # Legacy locations (including older macOS links): ~/OneDrive*
    def _legacy_priority(path: Path) -> tuple[bool, str]:
        name = path.name.lower()
        is_personal = name == "onedrive" or "personal" in name
        return (is_personal, name)

    legacy = sorted(
        (p for p in home.glob("OneDrive*") if p.is_dir()),
        key=_legacy_priority,
    )
    if legacy:
        return legacy[0]

    return None


def resolve_sync_folder() -> Path | None:
    """Discover the sync folder using the priority chain.

    Returns *None* when sync is explicitly disabled or no suitable root is
    found.

    Priority:
    1. Explicit ``sync.folder`` in dashboard-config.json
    2. ``%OneDriveCommercial%``
    3. ``%OneDriveConsumer%``
    4. OneDrive auto-discovery (macOS CloudStorage / legacy paths)
    5. User Documents folder
    Disabled if ``sync.enabled`` is ``false``
    """
    cfg = _read_sync_config()

    if cfg.get("enabled") is False:
        return None

    # 1. Explicit override
    explicit = cfg.get("folder")
    if explicit and isinstance(explicit, str):
        p = Path(explicit)
        if p.is_dir():
            return p / SYNC_FOLDER_NAME
        logger.warning("Configured sync folder does not exist: %s", explicit)
        return None

    # 2-3. OneDrive env vars (prefer commercial)
    for env_var in ("OneDriveCommercial", "OneDriveConsumer"):
        val = os.environ.get(env_var)
        if val and Path(val).is_dir():
            return Path(val) / SYNC_FOLDER_NAME

    # 4. OneDrive auto-discovery (e.g., macOS CloudStorage / legacy OneDrive*)
    detected_onedrive = _find_onedrive_folder()
    if detected_onedrive is not None:
        return detected_onedrive / SYNC_FOLDER_NAME

    # 5. Documents folder
    docs = Path.home() / "Documents"
    if docs.is_dir():
        return docs / SYNC_FOLDER_NAME

    return None


# ── Export (write local state) ───────────────────────────────────────────────


def _ensure_dirs(sync_folder: Path) -> Path:
    """Create ``{sync_folder}/{hostname}/sessions/`` and return the machine dir."""
    machine_dir = sync_folder / get_machine_name()
    sessions_dir = machine_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return machine_dir


def export_sessions(sessions: list[dict], sync_folder: Path) -> None:
    """Write one JSON file per active session and update ``machine.json``.

    *sessions* should be the list of enriched session dicts for locally
    **active** sessions only.  Each file is written atomically (write to
    temp then rename) to avoid partial reads by the cloud-sync client.
    """
    machine_dir = _ensure_dirs(sync_folder)
    sessions_dir = machine_dir / "sessions"

    active_ids: set[str] = set()
    for s in sessions:
        sid = s.get("id", "")
        if not sid:
            continue
        active_ids.add(sid)

        payload = dict(s)
        payload["machine_name"] = get_machine_name()

        tmp = sessions_dir / f"{sid}.tmp"
        target = sessions_dir / f"{sid}.json"
        try:
            tmp.write_text(json.dumps(payload, default=str), encoding="utf-8")
            tmp.replace(target)
        except OSError as e:
            logger.debug("Failed to write session file %s: %s", target, e)

    # Clean up sessions that are no longer active
    cleanup_stale_sessions(active_ids, sessions_dir)

    # Write machine.json
    machine_info = {
        "hostname": get_machine_name(),
        "last_sync": datetime.now(UTC).isoformat(),
        "active_session_count": len(active_ids),
    }
    try:
        tmp = machine_dir / "machine.tmp"
        target = machine_dir / "machine.json"
        tmp.write_text(json.dumps(machine_info, default=str), encoding="utf-8")
        tmp.replace(target)
    except OSError as e:
        logger.debug("Failed to write machine.json: %s", e)


def cleanup_stale_sessions(active_ids: set[str], sessions_dir: Path) -> None:
    """Remove session JSON files that are no longer active."""
    if not sessions_dir.is_dir():
        return
    for f in sessions_dir.iterdir():
        if f.suffix == ".json":
            sid = f.stem
            if sid not in active_ids:
                try:
                    f.unlink()
                except OSError:
                    pass


# ── Import (read remote state) ──────────────────────────────────────────────


def read_remote_sessions(sync_folder: Path) -> list[dict]:
    """Read session data from all *other* machines in the sync folder.

    Skips the local machine's subfolder and ignores machines whose
    ``machine.json`` is older than ``SYNC_STALE_THRESHOLD``.
    """
    if not sync_folder.is_dir():
        return []

    local_name = get_machine_name()
    now = time.time()
    results: list[dict] = []

    for machine_dir in sync_folder.iterdir():
        if not machine_dir.is_dir():
            continue
        if machine_dir.name == local_name:
            continue

        # Check staleness via machine.json
        machine_file = machine_dir / "machine.json"
        if machine_file.is_file():
            try:
                info = json.loads(machine_file.read_text(encoding="utf-8"))
                last_sync = info.get("last_sync", "")
                if last_sync:
                    dt = datetime.fromisoformat(last_sync)
                    age = now - dt.timestamp()
                    if age > SYNC_STALE_THRESHOLD:
                        # Delete stale machine directory
                        try:
                            shutil.rmtree(machine_dir)
                            logger.info("Removed stale remote machine dir: %s", machine_dir.name)
                        except OSError as e:
                            logger.debug("Failed to remove stale dir %s: %s", machine_dir, e)
                        continue
            except Exception:
                continue
        else:
            continue

        sessions_dir = machine_dir / "sessions"
        if not sessions_dir.is_dir():
            continue

        for sf in sessions_dir.iterdir():
            if sf.suffix != ".json":
                continue
            try:
                data = json.loads(sf.read_text(encoding="utf-8"))
                data["machine_name"] = machine_dir.name
                data["is_running"] = True  # Remote active sessions are always "running"
                results.append(data)
            except Exception as e:
                logger.debug("Failed to read remote session %s: %s", sf, e)

    return results


# ── Config sync ──────────────────────────────────────────────────────────────


def sync_config_to_shared(sync_folder: Path) -> None:
    """Copy local ``dashboard-config.json`` to the shared config folder."""
    if not os.path.exists(DASHBOARD_CONFIG_PATH):
        return
    config_dir = sync_folder / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(DASHBOARD_CONFIG_PATH, config_dir / "dashboard-config.json")
    except OSError as e:
        logger.debug("Failed to sync config: %s", e)


def sync_config_from_shared(sync_folder: Path) -> None:
    """Import shared config if it is newer than the local copy."""
    shared = sync_folder / "config" / "dashboard-config.json"
    if not shared.is_file():
        return

    local_mtime = (
        os.path.getmtime(DASHBOARD_CONFIG_PATH) if os.path.exists(DASHBOARD_CONFIG_PATH) else 0
    )
    shared_mtime = os.path.getmtime(shared)

    if shared_mtime > local_mtime:
        try:
            shutil.copy2(str(shared), DASHBOARD_CONFIG_PATH)
            logger.info("Updated local config from shared sync folder")
        except OSError as e:
            logger.debug("Failed to import shared config: %s", e)
