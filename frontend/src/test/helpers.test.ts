/**
 * Tests for utility/helper functions — all pure, no mocking needed.
 */

import { describe, it, expect } from "vitest";
import {
  esc,
  filterSessions,
  splitActivePrevious,
  groupSessions,
  sortStarredFirst,
  listCardClass,
  STATE_LABELS,
} from "../utils/helpers";
import type { Session, ProcessInfo } from "../types";

/** Minimal session factory for tests. */
function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: "test-id",
    cwd: null,
    repository: null,
    branch: null,
    summary: "Test session",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T01:00:00Z",
    created_ago: "1 hour ago",
    time_ago: "1 hour ago",
    turn_count: 5,
    file_count: 3,
    checkpoint_count: 1,
    is_running: false,
    state: null,
    waiting_context: "",
    bg_tasks: 0,
    group: "General",
    recent_activity: null,
    restart_cmd: "copilot",
    mcp_servers: [],
    tool_calls: 10,
    subagent_runs: 2,
    intent: "",
    source: "copilot",
    machine_name: "",
    ...overrides,
  };
}

describe("esc()", () => {
  it("escapes HTML special characters", () => {
    expect(esc("<script>alert('xss')</script>")).toBe(
      "&lt;script&gt;alert('xss')&lt;/script&gt;",
    );
  });

  it("returns empty string for null/undefined", () => {
    expect(esc(null)).toBe("");
    expect(esc(undefined)).toBe("");
    expect(esc("")).toBe("");
  });

  it("passes through safe strings unchanged", () => {
    expect(esc("hello world")).toBe("hello world");
  });
});

describe("filterSessions()", () => {
  const sessions = [
    makeSession({ id: "1", summary: "Fix auth bug", repository: "org/auth" }),
    makeSession({ id: "2", summary: "Update docs", cwd: "/home/homer/docs" }),
    makeSession({ id: "3", summary: "Deploy service", branch: "main" }),
  ];

  it("returns all sessions when filter is empty", () => {
    expect(filterSessions(sessions, "")).toHaveLength(3);
  });

  it("filters by summary", () => {
    expect(filterSessions(sessions, "auth")).toHaveLength(1);
  });

  it("filters by repository", () => {
    expect(filterSessions(sessions, "org/auth")).toHaveLength(1);
  });

  it("is case-insensitive", () => {
    expect(filterSessions(sessions, "FIX")).toHaveLength(1);
  });

  it("filters by cwd", () => {
    expect(filterSessions(sessions, "homer")).toHaveLength(1);
  });
});

describe("splitActivePrevious()", () => {
  it("splits sessions by process presence", () => {
    const sessions = [
      makeSession({ id: "active-1", updated_at: new Date().toISOString() }),
      makeSession({ id: "prev-1", updated_at: new Date().toISOString() }),
    ];
    const processes: Record<string, ProcessInfo> = {
      "active-1": {
        pid: 100,
        parent_pid: 0,
        terminal_pid: 0,
        terminal_name: "",
        cmdline: "",
        yolo: false,
        state: "working",
        waiting_context: "",
        bg_tasks: 0,
        bg_task_list: [],
        mcp_servers: [],
        window_title: "",
      },
    };

    const { active, previous } = splitActivePrevious(sessions, processes);
    expect(active).toHaveLength(1);
    expect(active[0].id).toBe("active-1");
    expect(previous).toHaveLength(1);
    expect(previous[0].id).toBe("prev-1");
  });

  it("excludes sessions older than 5 days from previous", () => {
    const oldDate = new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString();
    const sessions = [makeSession({ id: "old", updated_at: oldDate })];
    const { previous } = splitActivePrevious(sessions, {});
    expect(previous).toHaveLength(0);
  });
});

describe("groupSessions()", () => {
  it("groups by the group field", () => {
    const sessions = [
      makeSession({ id: "1", group: "ProjectA" }),
      makeSession({ id: "2", group: "ProjectB" }),
      makeSession({ id: "3", group: "ProjectA" }),
    ];
    const groups = groupSessions(sessions);
    expect(groups).toHaveLength(2);
    // Sorted by size descending
    expect(groups[0][0]).toBe("ProjectA");
    expect(groups[0][1]).toHaveLength(2);
  });

  it("uses 'General' for missing group", () => {
    const sessions = [makeSession({ group: "" })];
    const groups = groupSessions(sessions);
    expect(groups[0][0]).toBe("General");
  });
});

describe("sortStarredFirst()", () => {
  it("puts starred sessions first", () => {
    const sessions = [
      makeSession({ id: "a", updated_at: "2026-01-01T03:00:00Z" }),
      makeSession({ id: "b", updated_at: "2026-01-01T02:00:00Z" }),
      makeSession({ id: "c", updated_at: "2026-01-01T01:00:00Z" }),
    ];
    const starred = new Set(["c"]);
    const sorted = sortStarredFirst(sessions, starred);
    expect(sorted[0].id).toBe("c");
  });

  it("puts running sessions before non-running", () => {
    const sessions = [
      makeSession({ id: "a", is_running: false, updated_at: "2026-01-01T03:00:00Z" }),
      makeSession({ id: "b", is_running: true, updated_at: "2026-01-01T01:00:00Z" }),
      makeSession({ id: "c", is_running: false, updated_at: "2026-01-01T02:00:00Z" }),
    ];
    const sorted = sortStarredFirst(sessions, new Set());
    expect(sorted[0].id).toBe("b");
  });

  it("sorts by updated_at within same priority", () => {
    const sessions = [
      makeSession({ id: "a", updated_at: "2026-01-01T01:00:00Z" }),
      makeSession({ id: "b", updated_at: "2026-01-01T03:00:00Z" }),
      makeSession({ id: "c", updated_at: "2026-01-01T02:00:00Z" }),
    ];
    const sorted = sortStarredFirst(sessions, new Set());
    expect(sorted.map(s => s.id)).toEqual(["b", "c", "a"]);
  });
});

describe("listCardClass()", () => {
  it("returns waiting-session for waiting state", () => {
    expect(listCardClass(true, "waiting")).toBe("waiting-session");
  });

  it("returns idle-session for idle state", () => {
    expect(listCardClass(true, "idle")).toBe("idle-session");
  });

  it("returns active-session for working state", () => {
    expect(listCardClass(true, "working")).toBe("active-session");
  });

  it("returns empty string for unknown state", () => {
    expect(listCardClass(true, "unknown")).toBe("");
  });

  it("returns empty string when not running", () => {
    expect(listCardClass(false, "working")).toBe("");
  });
});

describe("STATE_LABELS", () => {
  it("has labels for all known states", () => {
    expect(STATE_LABELS.waiting).toContain("Waiting");
    expect(STATE_LABELS.working).toContain("Working");
    expect(STATE_LABELS.thinking).toContain("Thinking");
    expect(STATE_LABELS.idle).toContain("Idle");
  });
});
