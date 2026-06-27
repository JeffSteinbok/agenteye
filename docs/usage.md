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
copilot-dashboard app

# Start minimized to tray (great for autostart)
copilot-dashboard app --hidden

# Custom port
copilot-dashboard app --port 8080
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
copilot-dashboard start

# Start in the background (detached)
copilot-dashboard start --background

# Start on a custom port (default: 5111)
copilot-dashboard start --port 8080
```

Then open **[http://localhost:5111](http://localhost:5111)** (or your custom port) in your browser.

## Managing the Server

```bash
# Check if the dashboard is running
copilot-dashboard status

# Stop a running dashboard
copilot-dashboard stop
```

## Upgrading

```bash
# Upgrade to the latest version (restarts automatically if running)
copilot-dashboard upgrade
```

This stops the server, upgrades the package via pip, and restarts it.

## Autostart at Login

{: .note }
> Autostart is supported on **Windows** (HKCU `Run` registry entry) and **macOS** (a per-user LaunchAgent). Linux support is planned.

```bash
# Start tray app on login (recommended)
copilot-dashboard autostart --mode app

# Start background server on login
copilot-dashboard autostart --mode server

# Autostart with a custom port
copilot-dashboard autostart --mode app --port 8080

# Remove the autostart entry
copilot-dashboard autostart-remove
```

When using `--mode app`, the dashboard starts minimized to tray (with `--hidden` flag) so you don't get a window popping up on login.

{: .note }
> **macOS:** The LaunchAgent is written to `~/Library/LaunchAgents/com.copilotdashboard.app.plist` and registered with the interpreter you ran `autostart` with (so it has the tray dependencies installed). It loads immediately and on every login. Quitting from the tray keeps it closed until the next login (no `KeepAlive`). Logs go to `~/Library/Logs/copilot-dashboard.{out,err}.log`.

## Command Reference

| Command | Description |
|:--------|:------------|
| `copilot-dashboard app` | Run as native tray app with window |
| `copilot-dashboard app --hidden` | Run tray app, start minimized to tray |
| `copilot-dashboard app --port PORT` | Tray app on a custom port |
| `copilot-dashboard start` | Start the dashboard server |
| `copilot-dashboard start --background` | Start detached in the background |
| `copilot-dashboard start --port PORT` | Start on a custom port |
| `copilot-dashboard stop` | Stop the running dashboard |
| `copilot-dashboard status` | Check server status |
| `copilot-dashboard upgrade` | Upgrade and restart |
| `copilot-dashboard autostart --mode app` | Enable tray app at login (Windows/macOS) |
| `copilot-dashboard autostart --mode server` | Enable background server at login (Windows/macOS) |
| `copilot-dashboard autostart --port PORT` | Autostart with custom port |
| `copilot-dashboard autostart-remove` | Remove login startup |
