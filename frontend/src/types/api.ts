/**
 * TypeScript type definitions matching the Python API responses.
 *
 * These interfaces mirror the Pydantic models in src/schemas.py. Keep them
 * in sync whenever the backend API changes.
 */

/** A single running background subagent task. */
export interface BackgroundTask {
  agent_name: string;
  description: string;
}

/** Matches Python ProcessInfo model (src/schemas.py). */
export interface ProcessInfo {
  pid: number;
  parent_pid: number;
  terminal_pid: number;
  terminal_name: string;
  cmdline: string;
  yolo: boolean;
  state: "waiting" | "working" | "thinking" | "idle" | "unknown";
  waiting_context: string;
  bg_tasks: number;
  bg_task_list: BackgroundTask[];
  mcp_servers: string[];
  window_title: string;
}

/** A session as returned by GET /api/sessions. */
export interface Session {
  id: string;
  cwd: string | null;
  repository: string | null;
  branch: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
  created_ago: string;
  time_ago: string;
  turn_count: number;
  file_count: number;
  checkpoint_count: number;
  is_running: boolean;
  state: string | null;
  waiting_context: string;
  bg_tasks: number;
  group: string;
  recent_activity: string | null;
  restart_cmd: string;
  mcp_servers: string[];
  tool_calls: number;
  subagent_runs: number;
  intent: string;
  source: "copilot" | "claude";
  machine_name: string;
}

/** Checkpoint detail returned within GET /api/session/:id. */
export interface Checkpoint {
  checkpoint_number: number;
  title: string | null;
  overview: string | null;
  next_steps: string | null;
}

/** Reference (commit, PR, issue) returned within GET /api/session/:id. */
export interface Ref {
  ref_type: string;
  ref_value: string;
}

/** Conversation turn returned within GET /api/session/:id. */
export interface Turn {
  turn_index: number;
  user_message: string | null;
  assistant_response: string | null;
}

/** Tool usage count returned within GET /api/session/:id. */
export interface ToolCount {
  name: string;
  count: number;
}

export interface PlanProgress {
  done: number;
  total: number;
}

export interface SessionPlan {
  path: string | null;
  content: string | null;
  mtime: string | null;
  progress: PlanProgress | null;
}

/** Full response from GET /api/session/:id. */
export interface SessionDetail {
  checkpoints: Checkpoint[];
  refs: Ref[];
  turns: Turn[];
  recent_output: string[];
  tool_counts: ToolCount[];
  files: string[];
}

/** Map of session_id → ProcessInfo from GET /api/processes. */
export type ProcessMap = Record<string, ProcessInfo>;

/** File frequency from GET /api/files. */
export interface FileFrequency {
  file_path: string;
  session_count: number;
}

/** GET /api/version response. */
export interface VersionInfo {
  current: string;
  latest: string | null;
  update_available: boolean;
}

/** GET /api/server-info response. */
export interface ServerInfo {
  pid: number;
  port: string;
  sync_folder: string | null;
  log_file: string | null;
  log_level: string;
}

/** GET /api/autostart response. */
export interface AutostartStatus {
  supported: boolean;
  enabled: boolean;
}

/** GET/PUT /api/settings response. */
export interface DashboardSettings {
  sync_enabled: boolean;
  log_level: string;
  mtime_active_threshold: number;
}
