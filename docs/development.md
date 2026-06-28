---
title: Development
layout: default
nav_order: 7
---

# Development Guide
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Setting Up

```bash
# Clone the repo
git clone https://github.com/JeffSteinbok/agenteye.git
cd agenteye

# Install Python dev dependencies
pip install -r requirements-dev.txt

# Build the React frontend (required before starting the server)
cd frontend
npm install
npm run build   # outputs to ../src/static/dist/
cd ..

# Start the dashboard on dev port
python -m src.session_dashboard start --port 5112
```

{: .important }
> The React frontend **must be built** before starting the server. The build output goes to `src/static/dist/` which the Python server serves as static files. If the dashboard shows a blank page, rebuild the frontend.

## Architecture

| Module | Role |
|:-------|:-----|
| `session_dashboard.py` | CLI entry point with `start`, `stop`, `status` subcommands |
| `dashboard_api.py` | FastAPI app with typed REST API, Pydantic response models, and static file serving |
| `schemas.py` | Pydantic response models for all API endpoints (auto-generates OpenAPI spec) |
| `constants.py` | Centralized constants — timeouts, paths, terminal names, grouping defaults |
| `process_tracker.py` | Detects running copilot processes, reads `events.jsonl` for session state, extracts MCP servers, and uses Win32 APIs for window focus |
| `models.py` | Typed data models (`ProcessInfo`, `EventData`, `SessionState`, `VersionCache`, `RunningCache`) shared across modules |
| `grouping.py` | Session grouping logic — derives project/area names from repository, CWD, or content keywords |

## Data Sources

| Source | What It Provides |
|:-------|:----------------|
| `~/.copilot/session-store.db` | Session metadata, turns, checkpoints, files, refs (read-only SQLite) |
| `~/.copilot/session-state/<id>/events.jsonl` | Live session state, MCP config, recent tool output |
| Running `copilot.exe` processes | Active session detection, `--yolo` flag, MCP config file paths |

## Data Models

The codebase uses typed dataclasses and TypedDicts (defined in `src/models.py`) instead of raw dicts:

- **`ProcessInfo`** — running copilot process: pid, terminal info, state, yolo, mcp_servers
- **`EventData`** — parsed from `events.jsonl`: mcp_servers, tool_calls, cwd, branch, intent
- **`SessionState`** — TypedDict with state, waiting_context, bg_tasks
- **`VersionCache`** / **`RunningCache`** — typed TTL cache structures

## Frontend

The frontend is a React/TypeScript app built with Vite:

```
frontend/
├── src/
│   ├── components/   # React components
│   ├── hooks/        # Custom React hooks
│   ├── types/        # TypeScript type definitions
│   └── App.tsx       # Root component
├── package.json
└── vite.config.ts
```

For active frontend development, run the Vite dev server:

```bash
cd frontend
npm run dev    # proxies API calls to http://localhost:5112
```

The Python backend must still be running on port 5112 for API calls to work.

## Testing

```bash
# Run tests
python -m pytest tests/ -v --tb=short

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

## Linting & Type Checking

```bash
# Lint
ruff check src/

# Format
ruff format src/

# Type check
mypy src/
```

All three checks must pass before submitting a PR.
