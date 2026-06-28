---
title: API Reference
layout: default
nav_order: 6
---

# API Reference
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

The dashboard exposes a REST API that powers the web UI. All endpoints return JSON unless otherwise noted.

{: .note }
> The full OpenAPI specification is available at [`openapi.json`](https://github.com/JeffSteinbok/agenteye/blob/main/docs/openapi.json). You can view it interactively in the [Swagger Editor](https://editor.swagger.io/?url=https://raw.githubusercontent.com/JeffSteinbok/agenteye/main/docs/openapi.json).

## Endpoints

### Dashboard UI

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/` | Serves the dashboard web UI |

### Sessions

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/sessions` | All sessions with metadata, groups, and restart commands |
| `GET` | `/api/session/{id}` | Session detail — checkpoints, refs, recent output, turns |

#### `GET /api/sessions`

Returns all known sessions organized by group, including both active (running) and previous (from session store) sessions.

**Response fields:**

| Field | Type | Description |
|:------|:-----|:------------|
| `groups` | `object` | Sessions grouped by project name |
| `active_count` | `integer` | Number of currently active sessions |
| `previous_count` | `integer` | Number of previous sessions |

#### `GET /api/session/{id}`

Returns detailed information for a single session.

**Response fields:**

| Field | Type | Description |
|:------|:-----|:------------|
| `checkpoints` | `array` | Milestone summaries with titles and overviews |
| `refs` | `array` | Linked PRs, issues, and commits |
| `recent_output` | `string` | Latest tool output from the session |
| `turns` | `array` | Conversation history (user messages and assistant responses) |

### Processes

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/processes` | Currently running sessions with state, yolo mode, and MCP servers |

### Actions

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `POST` | `/api/focus/{id}` | Bring a session's terminal window to the foreground |
| `POST` | `/api/kill/{id}` | Kill a running session process |

### Files

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/files` | Most-edited files across all sessions |

### Server Management

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `GET` | `/api/version` | Current installed version + PyPI update check |
| `POST` | `/api/update` | Trigger pip upgrade and server restart |
| `GET` | `/api/server-info` | Server PID and port |

## Using the API

The API is available at `http://localhost:5111` (or your custom port) whenever the dashboard is running.

### Example: Get Active Sessions

```bash
curl http://localhost:5111/api/sessions | python -m json.tool
```

### Example: Get Session Detail

```bash
curl http://localhost:5111/api/session/abc-123-def | python -m json.tool
```

### Example: Focus a Session Window

```bash
curl -X POST http://localhost:5111/api/focus/abc-123-def
```

### Example: Check Version

```bash
curl http://localhost:5111/api/version
```
