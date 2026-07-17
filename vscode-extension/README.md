# AgentEye for VS Code

Monitor your Copilot CLI and Claude Code sessions from within VS Code.

## Features

- **Dashboard tab** — full AgentEye dashboard embedded as an editor tab
- **Status bar** — active session count at a glance
- **Auto-connect** — detects a running AgentEye server and connects immediately
- **Activity bar** — quick access icon with "Open/Focus Dashboard" button

## Requirements

- [AgentEye](https://github.com/jeffsteinbok/agenteye) backend running on localhost
- Install via: `pipx install agenteye-app`

## Usage

1. Start AgentEye (`agenteye start` or via the system tray app)
2. Open VS Code — the extension auto-detects the running server
3. The dashboard opens as an editor tab showing your active sessions

### Commands

| Command | Description |
|---------|-------------|
| `AgentEye: Open Dashboard` | Open or focus the dashboard tab |
| `AgentEye: Stop Backend` | Stop the AgentEye server |

## Extension Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `agenteye.port` | `5111` | Port for the AgentEye backend server |
| `agenteye.pythonPath` | (auto) | Path to Python or agenteye executable |
| `agenteye.showStatusBar` | `true` | Show session count in the status bar |

## Architecture

This extension is a thin frontend — it does NOT bundle or manage the Python backend lifecycle beyond basic start/stop. The server is expected to already be running (started by the CLI, tray app, or another VS Code window).

```
┌─────────────────────┐     HTTP     ┌──────────────────────┐
│  VS Code Extension  │◄────────────►│  AgentEye Backend    │
│  (webview iframe)   │  :5111       │  (FastAPI + React)   │
└─────────────────────┘              └──────────────────────┘
```

### Auth

AgentEye generates a per-instance API token. The extension extracts it from the root HTML page (`window.__DASHBOARD_TOKEN__`) and uses it for API calls. The iframe loads `/` directly which has the token pre-injected.

## Development

```bash
# Install dependencies
npm install

# Build (development)
npx webpack --mode development

# Watch mode
npm run watch

# Launch Extension Development Host
# Press F5 in VS Code with this folder open
```

### Project Structure

```
src/
├── extension.ts      Entry point — wires commands, backend, status bar
├── backend.ts        Backend manager — detection, health, startup, token extraction
├── environment.ts    Python/binary resolution chain
├── webview.ts        Editor tab webview rendering (all states)
└── statusBar.ts      Status bar item (session count)
```

## License

MIT
