"""
Pydantic response models for the FastAPI dashboard API.

These define the JSON shapes for all API endpoints and give us
automatic OpenAPI schema generation + Swagger UI.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ── Session list (/api/sessions) ─────────────────────────────────────────────


class SessionResponse(BaseModel):
    """A session as returned by GET /api/sessions."""

    id: str
    cwd: str | None = None
    repository: str | None = None
    branch: str | None = None
    summary: str | None = None
    created_at: str
    updated_at: str
    created_ago: str = ""
    time_ago: str = ""
    turn_count: int = 0
    file_count: int = 0
    checkpoint_count: int = 0
    is_running: bool = False
    state: str | None = None
    waiting_context: str = ""
    bg_tasks: int = 0
    group: str = "General"
    recent_activity: str | None = None
    restart_cmd: str = ""
    mcp_servers: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    subagent_runs: int = 0
    intent: str = ""
    source: str = "copilot"
    machine_name: str = ""


# ── Process map (/api/processes) ─────────────────────────────────────────────


class BackgroundTaskResponse(BaseModel):
    """A single running background subagent task."""

    agent_name: str = ""
    description: str = ""


class ProcessResponse(BaseModel):
    """A running Copilot process as returned by GET /api/processes."""

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
    bg_task_list: list[BackgroundTaskResponse] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    window_title: str = ""


# ── Session detail (/api/session/{id}) ───────────────────────────────────────


class CheckpointResponse(BaseModel):
    checkpoint_number: int
    title: str | None = None
    overview: str | None = None
    next_steps: str | None = None


class RefResponse(BaseModel):
    ref_type: str
    ref_value: str


class TurnResponse(BaseModel):
    turn_index: int
    user_message: str | None = None
    assistant_response: str | None = None


class ToolCountResponse(BaseModel):
    name: str
    count: int


class SessionDetailResponse(BaseModel):
    checkpoints: list[CheckpointResponse] = Field(default_factory=list)
    refs: list[RefResponse] = Field(default_factory=list)
    turns: list[TurnResponse] = Field(default_factory=list)
    recent_output: list[str] = Field(default_factory=list)
    tool_counts: list[ToolCountResponse] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)


# ── Files (/api/files) ──────────────────────────────────────────────────────


class FileEntryResponse(BaseModel):
    file_path: str
    session_count: int
    session_ids: str  # comma-separated


# ── Version (/api/version) ──────────────────────────────────────────────────


class VersionResponse(BaseModel):
    current: str
    latest: str | None = None
    update_available: bool = False


# ── Generic ─────────────────────────────────────────────────────────────────


class ActionResponse(BaseModel):
    """Generic success/failure response for POST actions."""

    success: bool
    message: str = ""


class ServerInfoResponse(BaseModel):
    pid: int
    port: str
    sync_folder: str | None = None
    log_file: str | None = None
    log_level: str = "INFO"


class AutostartStatusResponse(BaseModel):
    """Response for GET /api/autostart — reports whether autostart is supported and enabled."""

    supported: bool
    enabled: bool


class SettingsResponse(BaseModel):
    """Response for GET/PUT /api/settings — dashboard configuration."""

    sync_enabled: bool = True
    log_level: str = "INFO"
    mtime_active_threshold: int = 120
