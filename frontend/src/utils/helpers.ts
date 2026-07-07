/**
 * Shared utility functions used across components.
 *
 * These are pure functions with no React dependency — easy to unit test.
 */

import {
  PREVIOUS_SESSION_WINDOW_MS,
  STATE_BADGE_CLASS,
  STATE_LABELS,
  TILE_STATE_CLASS,
} from "../constants";
import type { Session, ProcessInfo } from "../types";

// Re-export the constant lookup tables so existing imports keep working
export { STATE_LABELS, STATE_BADGE_CLASS, TILE_STATE_CLASS };

/**
 * HTML-escape a string to prevent XSS.
 */
export function esc(s: string | null | undefined): string {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

/** CSS class for list cards by state. */
export function listCardClass(
  isRunning: boolean,
  state: string,
): string {
  if (!isRunning) return "";
  if (state === "waiting") return "waiting-session";
  if (state === "idle") return "idle-session";
  if (state === "working" || state === "thinking") return "active-session";
  return "";
}

/**
 * Group sessions by their `group` field, sorted by group size descending.
 * Returns [groupName, sessions][] pairs.
 */
export function groupSessions(
  sessions: Session[],
): [string, Session[]][] {
  return groupSessionsBy(sessions, "project");
}

/**
 * Group sessions by a chosen key: project (repo/cwd), machine, or none.
 * Returns [groupName, sessions][] pairs sorted by group size descending.
 */
export function groupSessionsBy(
  sessions: Session[],
  groupBy: "none" | "project" | "machine",
): [string, Session[]][] {
  if (groupBy === "none") return [["All Sessions", sessions]];

  const groups: Record<string, Session[]> = {};
  for (const s of sessions) {
    let key: string;
    if (groupBy === "machine") {
      key = s.machine_name || "Local";
    } else {
      key = s.group || "General";
    }
    (groups[key] ??= []).push(s);
  }
  return Object.entries(groups).sort((a, b) => b[1].length - a[1].length);
}

/**
 * Filter sessions matching a search string against summary, repo,
 * branch, cwd, group, intent, and MCP servers.
 */
export function filterSessions(
  sessions: Session[],
  filter: string,
): Session[] {
  if (!filter) return sessions;
  const lower = filter.toLowerCase();
  return sessions.filter((s) => {
    const hay = [
      s.summary,
      s.repository,
      s.branch,
      s.cwd,
      s.group,
      s.intent,
      ...(s.mcp_servers || []),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return hay.includes(lower);
  });
}

/**
 * Split sessions into active (has running process) and previous
 * (completed within the last 5 days).
 */
export function splitActivePrevious(
  sessions: Session[],
  processes: Record<string, ProcessInfo>,
): { active: Session[]; previous: Session[] } {
  const cutoff = Date.now() - PREVIOUS_SESSION_WINDOW_MS;
  const active: Session[] = [];
  const previous: Session[] = [];

  for (const s of sessions) {
    if (processes[s.id]) {
      active.push(s);
    } else if (new Date(s.updated_at).getTime() >= cutoff) {
      previous.push(s);
    }
  }
  return { active, previous };
}

/**
 * Sort sessions with starred items first.
 * Preserves original order within each group (starred / unstarred).
 */
const STATE_PRIORITY: Record<string, number> = {
  working: 0,
  thinking: 1,
  waiting: 2,
  idle: 3,
  unknown: 4,
};

export function sortStarredFirst(
  sessions: Session[],
  starred: Set<string>,
): Session[] {
  return [...sessions].sort((a, b) => {
    // Running sessions first
    if (a.is_running !== b.is_running) return a.is_running ? -1 : 1;
    // Then starred
    if (starred.size > 0) {
      const sa = starred.has(a.id) ? 1 : 0;
      const sb = starred.has(b.id) ? 1 : 0;
      if (sa !== sb) return sb - sa;
    }
    // Among running: sort by state (working > thinking > waiting > idle)
    if (a.is_running && b.is_running && a.state !== b.state) {
      const pa = STATE_PRIORITY[a.state ?? "unknown"] ?? 4;
      const pb = STATE_PRIORITY[b.state ?? "unknown"] ?? 4;
      if (pa !== pb) return pa - pb;
    }
    // Then by most recent activity (updated_at descending)
    return b.updated_at.localeCompare(a.updated_at);
  });
}
