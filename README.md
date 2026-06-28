<table border="0"><tr>
<td valign="middle"><img src="https://raw.githubusercontent.com/JeffSteinbok/agenteye/main/src/static/logo.png" height="48"></td>
<td valign="middle"><h1>Agent Eye</h1></td>
</tr></table>

[![GitHub](https://img.shields.io/badge/GitHub-agenteye-blue?logo=github)](https://github.com/JeffSteinbok/agenteye)
[![GitHub release](https://img.shields.io/github/v/release/JeffSteinbok/agenteye)](https://github.com/JeffSteinbok/agenteye/releases)

[![CI](https://github.com/JeffSteinbok/agenteye/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffSteinbok/agenteye/actions/workflows/ci.yml)
[![Release](https://github.com/JeffSteinbok/agenteye/actions/workflows/release.yml/badge.svg)](https://github.com/JeffSteinbok/agenteye/actions/workflows/release.yml)

[![Publish to PyPI](https://github.com/JeffSteinbok/agenteye/actions/workflows/publish-pypi.yml/badge.svg)](https://github.com/JeffSteinbok/agenteye/actions/workflows/publish-pypi.yml)
[![PyPI version](https://img.shields.io/pypi/v/agenteye-app.svg)](https://pypi.org/project/agenteye-app/)
[![OpenAPI](https://img.shields.io/badge/OpenAPI-spec-green?logo=openapiinitiative)](https://editor.swagger.io/?url=https://raw.githubusercontent.com/JeffSteinbok/agenteye/main/docs/openapi.json)

A local web dashboard that monitors all your GitHub Copilot CLI and Claude Code sessions in real-time.
Designed for power users running multiple AI coding sessions simultaneously.

> [!TIP]
> The dashboard works out of the box by reading `events.jsonl` files from your Copilot session directories. For richer session history (summaries, checkpoints), enable the **SESSION_STORE** experimental feature: add `"experimental": true` to `~/.copilot/config.json` and start a new Copilot session.

![Dashboard Screenshot](https://raw.githubusercontent.com/JeffSteinbok/agenteye/main/screenshot.png)

## Installation

### Option 1: From PyPI

```bash
pip install agenteye-app
```

### Option 2: From Source

```bash
# Clone the repo
git clone https://github.com/JeffSteinbok/agenteye.git
cd agenteye

# Install in editable mode
pip install -e .
```

## Usage

### Native App (Recommended)

Run as a native desktop app with system tray integration:

```bash
# Start the tray app (window + tray icon)
agenteye app

# Start minimized to tray
agenteye app --hidden

# Custom port
agenteye app --port 8080
```

The tray app provides:
- Native window with dark/light title bar matching app theme
- System tray icon with quick access menu
- Close (X) minimizes to tray, quit from tray menu exits
- Native Windows notifications (no browser permission needed)

### Browser Mode

Run as a background server and open in your browser:

```bash
# Start the dashboard
agenteye start

# Start in background
agenteye start --background

# Check status
agenteye status

# Stop
agenteye stop

# Upgrade to the latest version (restarts automatically if running)
agenteye upgrade
```

Open **http://localhost:5111** in your browser.

### Autostart at Login (Windows)

```bash
# Start tray app on login (recommended)
agenteye autostart --mode app

# Start background server on login
agenteye autostart --mode server

# Custom port
agenteye autostart --mode app --port 8080

# Remove login startup
agenteye autostart-remove
```

## Features

### Session States
- **Working / Thinking** (green) — session is actively running tools or reasoning
- **Waiting** (yellow) — session needs your input (`ask_user` or `ask_permission` pending)
- **Idle** (blue) — session is done and ready for your next task

### Key Features
- **Native tray app** — `agenteye app` runs as a native desktop application with system tray integration, eliminating the need for a separate browser tab
- **Dark/light title bar** — window title bar automatically matches your chosen theme
- **Native notifications** — Windows toast notifications with proper app name and icon (no browser permission prompts)
- **Start hidden** — `--hidden` flag starts the app minimized to tray (great for autostart)
- **Claude Code support** — automatically discovers Claude Code sessions from `~/.claude/projects/`. Active Claude sessions appear alongside Copilot sessions with a `✦ Claude` badge.
- **Cross-machine sync** — see active sessions from all your machines in one dashboard, powered by OneDrive or any cloud-synced folder. See [Cross-Machine Sync](#cross-machine-sync) for details.
- **Settings menu** — ☰ hamburger menu in the header with toggles for autostart-on-login and remote sync.
- **Upgrade command** — `agenteye upgrade` stops the server, upgrades via pip, and restarts automatically.
- **Desktop notifications** — get alerts when sessions transition between states
- **Focus window** — bring an active session's terminal to the foreground with one click
- **Restart commands** — copy-pasteable `copilot --resume <id>` commands for every session
- **Waiting context** — shows *what* a waiting session is asking (e.g. the `ask_user` question and choices)
- **Background tasks** — shows count of running subagents per session
- **Session details** — click any session to see checkpoints, recent tool output, references, and conversation history
- **Tile & List views** — compact card grid or detailed expandable rows
- **9 color palettes** and light/dark mode

### Cross-Machine Sync

See active sessions from all your machines in one dashboard — powered by OneDrive, Google Drive, or any cloud-synced folder. No Git commits needed.

**How it works:**
- On each poll cycle, the dashboard exports your active sessions as JSON files to a shared cloud folder
- Other machines read those files and display them in a **"Remote Sessions"** section under Active
- Each machine only writes to its own subfolder — no sync conflicts

**Auto-detection (priority order):**
1. `OneDriveCommercial` (preferred — prevents data leakage to personal accounts)
2. `OneDriveConsumer`
3. User Documents folder

**Configuration** (`~/.copilot/dashboard-config.json`):
```json
{
  "sync": {
    "enabled": true,
    "folder": "D:\\MyCloudSync"
  }
}
```
- Set `"enabled": false` to disable sync entirely
- Set `"folder"` to override auto-detection with a specific path

**What remote sessions show:**
- Live state indicators (working, waiting, idle)
- Session summary, intent, branch, MCP servers, turn/checkpoint counts
- Machine name badge (e.g. `🖥️ LAPTOP-HOME`)

**What remote sessions don't show:**
- No detail drill-down (checkpoints, turns, files)
- No focus or kill actions (those are local-only)
- No past/previous sessions from remote machines

## Prerequisites

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework with auto-generated OpenAPI docs |
| `uvicorn` | ASGI server |
| `pywinauto` | Window focus and process detection (Windows-only) |
| `pywebview` | Native window for tray app |
| `pystray` | System tray icon |
| `plyer` | Native OS notifications |

All are installed automatically via `pip install agenteye-app`.

For more details on architecture, data sources, and API endpoints, see [DEVELOPMENT.md](DEVELOPMENT.md).
