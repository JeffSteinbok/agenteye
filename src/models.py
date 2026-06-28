"""Typed data models for the Agent Eye."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass
class ProcessInfo:
    """Information about a running copilot process."""

    pid: int
    parent_pid: int = 0
    terminal_pid: int = 0
    terminal_name: str = ""
    cmdline: str = ""
    yolo: bool = False
    agency: bool = False
    state: str = "unknown"
    waiting_context: str = ""
    bg_tasks: int = 0
    bg_task_list: list[BackgroundTask] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    window_title: str = ""
    terminal_hwnd: int = 0


@dataclass
class EventData:
    """Parsed event data from a session's events.jsonl."""

    mcp_servers: list[str] = field(default_factory=list)
    tool_calls: int = 0
    subagent_runs: int = 0
    cwd: str = ""
    branch: str = ""
    repository: str = ""
    intent: str = ""


class BackgroundTask(TypedDict):
    """A single running background subagent task."""

    agent_name: str
    description: str


class SessionState(TypedDict):
    """State of a running session."""

    state: str  # 'waiting' | 'idle' | 'working' | 'thinking' | 'unknown'
    waiting_context: str
    bg_tasks: int
    bg_task_list: list[BackgroundTask]


@dataclass
class VersionCache:
    """Cached PyPI version check result."""

    latest: str | None = None
    update_available: bool = False
    checked_at: float = 0.0


@dataclass
class RunningCache:
    """TTL cache for running session process data."""

    data: dict[str, ProcessInfo] = field(default_factory=dict)
    time: float = 0.0
