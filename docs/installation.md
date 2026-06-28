---
title: Installation
layout: default
nav_order: 2
---

# Installation
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## From PyPI (Recommended)

The simplest way to install:

```bash
pip install agenteye
```

This installs the `agenteye` command and all required dependencies.

## From Source

```bash
# Clone the repo
git clone https://github.com/JeffSteinbok/agenteye.git
cd agenteye

# Install in editable mode
pip install -e .
```

## Dependencies

These are installed automatically — no manual setup needed:

| Package | Purpose |
|:--------|:--------|
| `fastapi` | Web framework with auto-generated OpenAPI docs |
| `uvicorn` | ASGI server |
| `pywin32` | Window focus and process detection (Windows-only) |

## Prerequisites

- **Python 3.10+**
- **GitHub Copilot CLI** — the dashboard reads Copilot's session data from `~/.copilot/`
- **Windows** — currently optimized for Windows (uses `pywin32` for window management)

## Upgrading

```bash
# Upgrade via pip
pip install --upgrade agenteye

# Or use the built-in upgrade command (restarts automatically if running)
agenteye upgrade
```

## Verifying Installation

```bash
agenteye --help
```

You should see the available commands: `start`, `stop`, `status`, `upgrade`, `autostart`, and `autostart-remove`.
