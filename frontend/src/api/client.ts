/**
 * Typed API client for the Agent Eye backend.
 *
 * Each function maps 1:1 to a FastAPI route in dashboard_api.py.
 * All responses are typed to match the Pydantic models (src/schemas.py).
 *
 * All /api/* requests include a per-instance auth token injected by the
 * server into window.__DASHBOARD_TOKEN__ at page load.
 */

import type {
  Session,
  SessionDetail,
  ProcessMap,
  FileFrequency,
  VersionInfo,
  ServerInfo,
  AutostartStatus,
  DashboardSettings,
} from "../types";

/** Read the auth token injected by the server into the HTML page. */
function getToken(): string {
  return window.__DASHBOARD_TOKEN__ ?? "";
}

/** Append the auth token as a query parameter. */
function withToken(url: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}token=${encodeURIComponent(getToken())}`;
}

/** Generic GET helper — throws on non-2xx responses. */
async function get<T>(url: string): Promise<T> {
  const resp = await fetch(withToken(url));
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

/** Generic POST helper — throws on non-2xx responses. */
async function post<T>(url: string): Promise<T> {
  const resp = await fetch(withToken(url), { method: "POST" });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

/** Generic PUT+JSON helper — throws on non-2xx responses. */
async function put<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(withToken(url), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
  return resp.json() as Promise<T>;
}

// ── Session data ─────────────────────────────────────────────────────────────

/** Fetch all sessions with enriched metadata (groups, restart cmds, etc.). */
export function fetchSessions(): Promise<Session[]> {
  return get<Session[]>("/api/sessions");
}

/** Fetch detailed info for a single session (checkpoints, turns, refs). */
export function fetchSessionDetail(id: string): Promise<SessionDetail> {
  return get<SessionDetail>(`/api/session/${id}`);
}

/** Fetch files most frequently edited across recent sessions. */
export function fetchFiles(): Promise<FileFrequency[]> {
  return get<FileFrequency[]>("/api/files");
}

// ── Process tracking ─────────────────────────────────────────────────────────

/** Fetch currently-running Copilot processes, keyed by session ID. */
export function fetchProcesses(): Promise<ProcessMap> {
  return get<ProcessMap>("/api/processes");
}

/** Bring a session's terminal window to the foreground (Windows only). */
export function focusSession(
  id: string,
): Promise<{ success: boolean; message: string }> {
  return post(`/api/focus/${id}`);
}

/** Kill a running session's process. */
export function killSession(
  id: string,
): Promise<{ success: boolean; message: string }> {
  return post(`/api/kill/${encodeURIComponent(id)}`);
}

// ── Remote sessions (cross-machine sync) ─────────────────────────────────────

/** Fetch active sessions from other machines via the sync folder. */
export function fetchRemoteSessions(): Promise<Session[]> {
  return get<Session[]>("/api/remote-sessions");
}

// ── Server management ────────────────────────────────────────────────────────

/** Check for a newer version on PyPI. */
export function fetchVersion(): Promise<VersionInfo> {
  return get<VersionInfo>("/api/version");
}

/** Get the dashboard server's PID and port. */
export function fetchServerInfo(): Promise<ServerInfo> {
  return get<ServerInfo>("/api/server-info");
}

/**
 * Trigger a self-update via pip. The server dies mid-response while
 * upgrading itself, so fetch errors are expected and swallowed.
 */
export async function triggerUpdate(): Promise<void> {
  try {
    await fetch(withToken("/api/update"), { method: "POST" });
  } catch {
    // Server dies mid-response during self-update — this is expected
  }
}

// ── Autostart ────────────────────────────────────────────────────────────────

/** Check whether autostart is supported and currently enabled. */
export function fetchAutostartStatus(): Promise<AutostartStatus> {
  return get<AutostartStatus>("/api/autostart");
}

/** Enable autostart via the backend (Windows Task Scheduler). */
export function enableAutostart(): Promise<{ success: boolean; message: string }> {
  return post("/api/autostart/enable");
}

/** Disable autostart via the backend. */
export function disableAutostart(): Promise<{ success: boolean; message: string }> {
  return post("/api/autostart/disable");
}

// ── Settings ─────────────────────────────────────────────────────────────────

/** Fetch current dashboard settings (sync toggle, etc.). */
export function fetchSettings(): Promise<DashboardSettings> {
  return get<DashboardSettings>("/api/settings");
}

/** Update dashboard settings. */
export function updateSettings(
  patch: Partial<DashboardSettings>,
): Promise<DashboardSettings> {
  return put<DashboardSettings>("/api/settings", patch);
}
