---
title: Home
layout: home
nav_order: 1
---

# Agent Eye

[![GitHub release](https://img.shields.io/github/v/release/JeffSteinbok/agenteye)](https://github.com/JeffSteinbok/agenteye/releases)
[![PyPI version](https://img.shields.io/pypi/v/agenteye.svg)](https://pypi.org/project/agenteye/)
[![CI](https://github.com/JeffSteinbok/agenteye/actions/workflows/ci.yml/badge.svg)](https://github.com/JeffSteinbok/agenteye/actions/workflows/ci.yml)

A local web dashboard that monitors all your **GitHub Copilot CLI** and **Claude Code** sessions in real-time. Designed for power users running multiple AI coding sessions simultaneously.
{: .fs-6 .fw-300 }

[Get Started]({{ site.baseurl }}/installation){: .btn .btn-primary .fs-5 .mb-4 .mb-md-0 .mr-2 }
[View on GitHub](https://github.com/JeffSteinbok/agenteye){: .btn .fs-5 .mb-4 .mb-md-0 }

---

![Dashboard Screenshot](https://raw.githubusercontent.com/JeffSteinbok/agenteye/main/screenshot.png)

## Quick Start

```bash
pip install agenteye
agenteye start
```

Open **[http://localhost:5111](http://localhost:5111)** in your browser — that's it!

{: .tip }
> The dashboard works out of the box by reading `events.jsonl` files from your Copilot session directories. For richer session history (summaries, checkpoints), enable the **SESSION_STORE** experimental feature: add `"experimental": true` to `~/.copilot/config.json` and start a new Copilot session.

## What You'll See

| State | Indicator | Meaning |
|:------|:----------|:--------|
| **Working / Thinking** | 🟢 Green | Session is actively running tools or reasoning |
| **Waiting** | 🟡 Yellow | Session needs your input (question or permission pending) |
| **Idle** | 🔵 Blue | Session is done and ready for your next task |

## Highlights

- **Multi-session monitoring** — see all your Copilot and Claude Code sessions at a glance
- **Desktop notifications** — get alerts when sessions change state
- **One-click focus** — bring any session's terminal to the foreground
- **Cross-machine sync** — see sessions from all your machines via OneDrive or cloud folders
- **9 color palettes** with light and dark mode
- **Tile & list views** — compact cards or detailed expandable rows
