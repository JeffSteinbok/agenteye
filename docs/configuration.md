---
title: Configuration
layout: default
nav_order: 5
---

# Configuration
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Configuration File

The dashboard reads its configuration from:

```
~/.copilot/dashboard-config.json
```

All settings are optional — the dashboard works out of the box with sensible defaults.

## Session Grouping

Sessions are grouped by project using a smart algorithm:

1. **Custom mappings** — user-defined keyword → group name
2. **Repository field** — `owner/repo` → uses the repo name
3. **CWD path** — last meaningful directory segment (skips common dirs like `Users`, `home`, drive letters)
4. **Content keywords** — fallback matching on summary/checkpoint text

### Custom Grouping

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

| Field | Type | Description |
|:------|:-----|:------------|
| `skip_dirs` | `string[]` | Directory names to skip when deriving project names from paths |
| `mappings` | `object` | Keyword → display name mappings for grouping |

## Cross-Machine Sync

See active sessions from all your machines in one dashboard — powered by OneDrive, Google Drive, or any cloud-synced folder.

### How It Works

1. On each poll cycle, the dashboard exports your active sessions as JSON files to a shared cloud folder
2. Other machines read those files and display them in a **"Remote Sessions"** section
3. Each machine only writes to its own subfolder — no sync conflicts

### Auto-Detection

The sync folder is auto-detected in this priority order:

1. `OneDriveCommercial` (preferred — prevents data leakage to personal accounts)
2. `OneDriveConsumer`
3. User Documents folder

### Sync Configuration

```json
{
  "sync": {
    "enabled": true,
    "folder": "D:\\MyCloudSync"
  }
}
```

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `enabled` | `boolean` | `true` | Set to `false` to disable sync entirely |
| `folder` | `string` | *(auto-detected)* | Override auto-detection with a specific path |

### What Remote Sessions Show

- ✅ Live state indicators (working, waiting, idle)
- ✅ Session summary, intent, branch, MCP servers
- ✅ Turn and checkpoint counts
- ✅ Machine name badge (e.g., `🖥️ LAPTOP-HOME`)

### What Remote Sessions Don't Show

- ❌ Detail drill-down (checkpoints, turns, files)
- ❌ Focus or kill actions (those are local-only)
- ❌ Past/previous sessions from remote machines

## Full Configuration Example

```json
{
  "grouping": {
    "skip_dirs": ["jeffs", "projects"],
    "mappings": {
      "ghcpCliDashboard": "AI CLI Agent Dashboard",
      "review": "Code Reviews",
      "docs": "Documentation"
    }
  },
  "sync": {
    "enabled": true,
    "folder": "D:\\OneDrive\\CopilotSync"
  }
}
```
