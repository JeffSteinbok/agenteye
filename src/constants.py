"""
Centralised constants for the AI CLI Agent Dashboard backend.

All magic numbers, timeouts, file-system paths, and hardcoded lists live
here so they are easy to find, tune, and test.
"""

from __future__ import annotations

import os

import platformdirs

# ── Python version ────────────────────────────────────────────────────────────

MIN_PYTHON_VERSION = (3, 11)
"""Minimum supported Python version — enforced by setup.py python_requires."""

# ── Network & server ──────────────────────────────────────────────────────────

DEFAULT_PORT = 5111
"""Default HTTP port for the dashboard server."""

LOCALHOST = "127.0.0.1"
"""Bind address — dashboard is local-only."""

PYPI_PACKAGE_URL = "https://pypi.org/pypi/ghcp-cli-dashboard/json"
"""PyPI JSON API endpoint for version checks."""

# ── File-system paths ─────────────────────────────────────────────────────────

COPILOT_DIR = os.path.join(os.path.expanduser("~"), ".copilot")
SESSION_STATE_DIR = os.path.join(COPILOT_DIR, "session-state")
SESSION_STORE_DB = os.path.join(COPILOT_DIR, "session-store.db")
DASHBOARD_CONFIG_PATH = os.path.join(COPILOT_DIR, "dashboard-config.json")

# Log directory uses OS-standard location via platformdirs:
#   Windows:  %LOCALAPPDATA%\ghcpCliDashboard\Logs\
#   macOS:    ~/Library/Logs/ghcpCliDashboard/
#   Linux:    ~/.local/state/ghcpCliDashboard/log/
DASHBOARD_LOG_DIR = platformdirs.user_log_dir("ghcpCliDashboard", appauthor=False)
DASHBOARD_LOG_FILE = os.path.join(DASHBOARD_LOG_DIR, "dashboard.log")

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
CLAUDE_PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")

# ── Polling & cache intervals (seconds) ──────────────────────────────────────

RUNNING_CACHE_TTL = 5
"""How long to cache the result of get_running_sessions()."""

VERSION_CACHE_TTL = 1800
"""How often to re-check PyPI for a new version (30 minutes)."""

EVENT_STALENESS_THRESHOLD = 60
"""Events older than this (seconds) are treated as stale / likely buffered."""

# ── Subprocess timeouts (seconds) ────────────────────────────────────────────

POWERSHELL_TIMEOUT = 30
"""Timeout for the main Win32_Process CIM query."""

PS_TIMEOUT = 10
"""Timeout for the Unix ``ps`` process listing."""

PARENT_LOOKUP_TIMEOUT = 5
"""Timeout for individual parent-process lookups (Unix + Windows)."""

OSASCRIPT_TIMEOUT = 5
"""Timeout for macOS AppleScript focus commands."""

PYTHON_VERSION_TIMEOUT = 5
"""Timeout when probing ``py --version`` at startup."""

PYPI_FETCH_TIMEOUT = 5
"""Timeout for the PyPI version-check HTTP request."""

# ── Buffer & truncation sizes ────────────────────────────────────────────────

EVENT_TAIL_BUFFER = 16_384
"""Bytes to read from the end of events.jsonl for recent-event parsing."""

OUTPUT_TAIL_BUFFER = 65_536
"""Bytes to read from the end of events.jsonl for recent-output extraction."""

RECENT_ACTIVITY_MAX_LEN = 120
"""Max characters for the ``recent_activity`` field before truncation."""

# ── Process tree traversal limits ────────────────────────────────────────────

MAX_ANCESTRY_DEPTH = 10
"""How far up the process tree to walk when looking for a terminal window."""

MAX_UNIX_PARENT_DEPTH = 5
"""Max parent hops on Unix when searching for a terminal ancestor."""

MAX_DIAGNOSTICS_CHAIN = 12
"""Max depth for the diagnostics ancestry chain logged during focus."""

PROCESS_MATCH_TOLERANCE = 30.0
"""Max seconds between process creation and session lifecycle events to count as a match."""

# ── Terminal / IDE process names ──────────────────────────────────────────────
# Used when walking the process tree to identify which ancestor owns the
# terminal GUI window.  Only GUI window-owning processes — not shells.

TERMINAL_NAMES: frozenset[str] = frozenset(
    {
        # Windows terminal apps
        "windowsterminal.exe",
        "wt.exe",
        "conemu64.exe",
        "conemu.exe",
        "cmder.exe",
        "mintty.exe",
        "alacritty.exe",
        "wezterm-gui.exe",
        "hyper.exe",
        "tabby.exe",
        "kitty.exe",
        "fluent-terminal.exe",
        # Windows IDEs
        "code.exe",
        "cursor.exe",
        # macOS terminal apps
        "iterm2",
        "terminal",
        "alacritty",
        "wezterm",
        "hyper",
        "kitty",
        "tabby",
        "warp",
        "nova",
        # macOS IDEs
        "code",
        "cursor",
        "xcode",
    }
)

UNIX_TERMINAL_SUBSTRINGS: tuple[str, ...] = (
    "terminal",
    "iterm",
    "alacritty",
    "kitty",
    "warp",
    "hyper",
    "wezterm",
    "windowserver",
)
"""Substrings checked against Unix process names to identify terminals."""

# macOS: map process-name substrings → AppleScript application names
MACOS_APP_NAMES: dict[str, str] = {
    "iterm": "iTerm",
    "terminal": "Terminal",
    "alacritty": "Alacritty",
    "kitty": "kitty",
    "warp": "Warp",
    "wezterm": "WezTerm",
}

MACOS_FALLBACK_TERMINALS: list[str] = ["Terminal", "iTerm", "Warp"]
"""Fallback list when the terminal name cannot be determined on macOS."""

# ── Grouping defaults ─────────────────────────────────────────────────────────

DEFAULT_GROUP_NAME = "General"
"""Fallback group name when no other grouping rule matches."""

# ── Cross-machine sync ────────────────────────────────────────────────────────

SYNC_FOLDER_NAME = "CopilotDashboard"
"""Subfolder name inside the cloud-sync root (OneDrive / Google Drive / Documents)."""

SYNC_EXPORT_INTERVAL = 30
"""How often to export local sessions to the sync folder (seconds)."""

SYNC_STALE_THRESHOLD = 14400
"""Ignore remote machine data older than this (seconds). 4 hours."""

# ── Grouping defaults ─────────────────────────────────────────────────────────

SKIP_DIRS: frozenset[str] = frozenset(
    {
        "",
        "c:",
        "d:",
        "e:",
        "q:",
        "users",
        "home",
        "src",
        "documents",
        "desktop",
        "projects",
        "repos",
        "github",
    }
)
"""Path segments to ignore when deriving a group name from CWD."""

KEYWORD_GROUPS: list[tuple[list[str], str]] = [
    (["code review", "pr review"], "PR Reviews"),
    (["pipeline", "build pipeline", "ci/cd"], "CI/CD Pipelines"),
    (["prune", "cleanup", "delete branch", "stale"], "Branch Cleanup"),
    (["dashboard", "monitor"], "Session Dashboard"),
    (["spec", "specification", "document"], "Specifications"),
]
"""Content-keyword → group-name mappings used as a last-resort fallback."""

# ── Time unit divisors (for time_ago display) ─────────────────────────────────

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_MAX_BYTES = 5 * 1024 * 1024
"""Max size of a single log file before rotation (5 MB)."""

LOG_BACKUP_COUNT = 3
"""Number of rotated log files to keep (dashboard.log.1, .2, .3)."""

DEFAULT_LOG_LEVEL = "INFO"
"""Default logging level when not overridden by config or CLI."""
