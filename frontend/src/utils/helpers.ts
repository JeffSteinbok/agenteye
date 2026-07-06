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
import type { Session, ProcessInfo, ProcessMap } from "../types";
import type { SortMode } from "../state";

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
  return "active-session";
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
  sortMode: SortMode = "default",
  statusChangedAt: Record<string, number> = {},
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
    // Among running sessions, order depends on the selected sort mode
    if (a.is_running && b.is_running) {
      if (sortMode === "status_changed") {
        // Most recently entered waiting/idle first; sessions that never became
        // actionable (no recorded timestamp) fall to the bottom of the group.
        const ta = statusChangedAt[a.id];
        const tb = statusChangedAt[b.id];
        const hasA = ta !== undefined;
        const hasB = tb !== undefined;
        if (hasA !== hasB) return hasA ? -1 : 1;
        if (hasA && hasB && ta !== tb) return tb - ta;
      } else if (a.state !== b.state) {
        // Default: sort by state (working > thinking > waiting > idle)
        const pa = STATE_PRIORITY[a.state ?? "unknown"] ?? 4;
        const pb = STATE_PRIORITY[b.state ?? "unknown"] ?? 4;
        if (pa !== pb) return pa - pb;
      }
    }
    // Then by most recent activity (updated_at descending)
    return b.updated_at.localeCompare(a.updated_at);
  });
}

/**
 * Diff two process polls and return the sessions that just entered an
 * actionable status (`waiting` or `idle`), mapped to the epoch-ms time of the
 * change. Only these transitions are interesting for the "recently changed
 * status" sort — `working`/`thinking` flips are ignored.
 *
 * - A genuine live transition (previous state known and different) is stamped
 *   with `now`.
 * - A session first seen already in waiting/idle is seeded from its
 *   `updated_at` (best proxy), but only when there is no existing recorded
 *   timestamp, so persisted values are never clobbered on reload.
 */
export function computeStatusChanges(
  oldP: ProcessMap,
  newP: ProcessMap,
  sessions: Session[],
  existing: Record<string, number>,
  now: number = Date.now(),
): Record<string, number> {
  const changes: Record<string, number> = {};
  for (const [sid, info] of Object.entries(newP)) {
    const st = info.state;
    if (st !== "waiting" && st !== "idle") continue;
    const oldState = oldP[sid]?.state;
    if (oldState === st) continue; // no transition
    if (!oldState) {
      if (existing[sid] === undefined) {
        const s = sessions.find((x) => x.id === sid);
        const ts = s?.updated_at ? Date.parse(s.updated_at) : NaN;
        changes[sid] = Number.isNaN(ts) ? now : ts;
      }
    } else {
      changes[sid] = now;
    }
  }
  return changes;
}
