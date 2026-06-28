---
title: Usage
layout: default
nav_order: 3
---

# Usage
{: .no_toc }

## Table of contents
{: .no_toc .text-delta }

1. TOC
{:toc}

---

## Native App Mode (Recommended)

Run as a native desktop application with system tray integration:

```bash
# Start the tray app (opens window + tray icon)
agenteye app

# Start minimized to tray (great for autostart)
agenteye app --hidden

# Custom port
agenteye app --port 8080
```

The native app provides:
- **Native window** with dark/light title bar matching your theme
- **System tray icon** with quick access menu (Show, Hide, Open in Browser, Quit)
- **Minimize to tray** — closing the window (X) hides it to tray instead of quitting
- **Native notifications** — Windows toast notifications without browser permission prompts

## Browser Mode

Run as a background server and open in your browser:

```bash
# Start in the foreground
agenteye start

# Start in the background (detached)
agenteye start --background

# Start on a custom port (default: 5111)
agenteye start --port 8080
```

Then open **[http://localhost:5111](http://localhost:5111)** (or your custom port) in your browser.

## Managing the Server

```bash
# Check if the dashboard is running
agenteye status

# Stop a running dashboard
agenteye stop
```

## Upgrading

```bash
# Upgrade to the latest version (restarts automatically if running)
agenteye upgrade
```

This stops the server, upgrades the package via pip, and restarts it.

## Autostart at Login

{: .note }
> Autostart is supported on **Windows** (HKCU `Run` registry entry) and **macOS** (a per-user LaunchAgent). Linux support is planned.

```bash
# Start tray app on login (recommended)
agenteye autostart --mode app

# Start background server on login
agenteye autostart --mode server

# Autostart with a custom port
agenteye autostart --mode app --port 8080

# Remove the autostart entry
agenteye autostart-remove
```

When using `--mode app`, the dashboard starts minimized to tray (with `--hidden` flag) so you don't get a window popping up on login.

{: .note }
> **macOS:** The LaunchAgent is written to `~/Library/LaunchAgents/com.agenteye.app.plist` and registered with the interpreter you ran `autostart` with (so it has the tray dependencies installed). It loads immediately and on every login. Quitting from the tray keeps it closed until the next login (no `KeepAlive`). Logs go to `~/Library/Logs/agenteye.{out,err}.log`.

## Command Reference

| Command | Description |
|:--------|:------------|
| `agenteye app` | Run as native tray app with window |
| `agenteye app --hidden` | Run tray app, start minimized to tray |
| `agenteye app --port PORT` | Tray app on a custom port |
| `agenteye start` | Start the dashboard server |
| `agenteye start --background` | Start detached in the background |
| `agenteye start --port PORT` | Start on a custom port |
| `agenteye stop` | Stop the running dashboard |
| `agenteye status` | Check server status |
| `agenteye upgrade` | Upgrade and restart |
| `agenteye autostart --mode app` | Enable tray app at login (Windows/macOS) |
| `agenteye autostart --mode server` | Enable background server at login (Windows/macOS) |
| `agenteye autostart --port PORT` | Autostart with custom port |
| `agenteye autostart-remove` | Remove login startup |
