# Development Guide

## Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | Web framework with auto-generated OpenAPI docs |
| `uvicorn` | ASGI server |
| `pywin32` | Window focus and process detection (Windows-only) |

Both are installed automatically when you `pip install agenteye-app`. For source installs, run `pip install -r requirements.txt` (plus `pip install pywin32` on Windows).

## Architecture

| Module | Role |
|--------|------|
| `session_dashboard.py` | CLI entry point with `start`, `stop`, `status` subcommands |
| `dashboard_api.py` | FastAPI app with typed REST API, Pydantic response models, and static file serving |
| `schemas.py` | Pydantic response models for all API endpoints (auto-generates OpenAPI spec) |
| `constants.py` | Centralised constants — timeouts, paths, terminal names, grouping defaults |
| `process_tracker.py` | Detects running copilot processes, reads `events.jsonl` for session state, extracts MCP servers, and uses Win32 APIs for window focus |
| `models.py` | Typed data models (`ProcessInfo`, `EventData`, `SessionState`, `VersionCache`, `RunningCache`) shared across modules |
| `grouping.py` | Session grouping logic — derives project/area names from repository, CWD, or content keywords. Supports user config via `~/.copilot/dashboard-config.json` |

## Data Sources

| Source | What it provides |
|--------|-----------------|
| `~/.copilot/session-store.db` | Session metadata, turns, checkpoints, files, refs (read-only SQLite) |
| `~/.copilot/session-state/<id>/events.jsonl` | Live session state, MCP config, recent tool output |
| Running `copilot.exe` processes | Active session detection, `--yolo` flag, MCP config file paths |

## Data Models

The codebase uses typed dataclasses and TypedDicts (defined in `src/models.py`) instead of raw dicts:

- **`ProcessInfo`** — running copilot process: pid, terminal info, state, yolo, mcp_servers
- **`EventData`** — parsed from `events.jsonl`: mcp_servers, tool_calls, cwd, branch, intent
- **`SessionState`** — TypedDict with state, waiting_context, bg_tasks
- **`VersionCache`** / **`RunningCache`** — typed TTL cache structures

## Session Grouping

Sessions are grouped by project using a generic algorithm (in `src/grouping.py`):

1. **Custom mappings** — user-defined keyword → group name via `~/.copilot/dashboard-config.json`
2. **Repository field** — `owner/repo` → uses repo name
3. **CWD path** — last meaningful directory segment (skips common dirs like `Users`, `home`, drive letters)
4. **Content keywords** — fallback matching on summary/checkpoint text

Custom config example (`~/.copilot/dashboard-config.json`):
```json
{
  "grouping": {
    "skip_dirs": ["myusername"],
    "mappings": {
      "myrepo": "My Project",
      "review": "Code Reviews"
    }
  }
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/sessions` | GET | All sessions with metadata, groups, restart commands |
| `/api/session/<id>` | GET | Session detail (checkpoints, refs, recent output, turns) |
| `/api/processes` | GET | Currently running sessions with state, yolo, MCP |
| `/api/focus/<id>` | POST | Bring session's terminal window to foreground |
| `/api/kill/<id>` | POST | Kill a running session process |
| `/api/files` | GET | Most-edited files across sessions |
| `/api/version` | GET | Current version + PyPI update check |
| `/api/update` | POST | Trigger pip upgrade and server restart |
| `/api/server-info` | GET | Server PID and port |

## Running Locally

```bash
# Install Python dev dependencies
pip install -r requirements-dev.txt

# Build the React frontend (required before starting the server)
cd frontend
npm install
npm run build   # outputs to ../src/static/dist/
cd ..

# Start the dashboard
python -m src.session_dashboard start --port 5112

# Run tests
python -m pytest tests/ -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing

# Lint & format
ruff check src/
ruff format src/

# Type check
mypy src/
```
