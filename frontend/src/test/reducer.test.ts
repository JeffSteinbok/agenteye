/**
 * Tests for the AppContext reducer — pure function, no React rendering needed.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { appReducer, initialState, isDisconnected } from "../state/AppContext";
import type { AppState } from "../state/AppContext";
import {
  STORAGE_KEY_STARRED,
  STORAGE_KEY_VIEW,
} from "../constants";

// Mock localStorage for initialState
const store: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, val: string) => { store[key] = val; },
  removeItem: (key: string) => { delete store[key]; },
});

let state: AppState;

beforeEach(() => {
  Object.keys(store).forEach((k) => delete store[k]);
  state = initialState();
});

describe("initialState()", () => {
  it("defaults to tile view and dark mode prefs", () => {
    expect(state.currentView).toBe("tile");
    expect(state.currentTab).toBe("active");
    expect(state.sessions).toEqual([]);
    expect(state.consecutiveFailures).toBe(0);
  });

  it("reads starred sessions from localStorage", () => {
    store[STORAGE_KEY_STARRED] = '["abc","def"]';
    const s = initialState();
    expect(s.starredSessions.has("abc")).toBe(true);
    expect(s.starredSessions.has("def")).toBe(true);
  });

  it("reads view preference from localStorage", () => {
    store[STORAGE_KEY_VIEW] = "list";
    const s = initialState();
    expect(s.currentView).toBe("list");
  });

  it("defaults groupBy to none", () => {
    expect(state.groupBy).toBe("none");
  });

  it("reads groupBy preference from localStorage", () => {
    store["dash-group-by"] = "machine";
    const s = initialState();
    expect(s.groupBy).toBe("machine");
  });

  it("ignores invalid groupBy in localStorage", () => {
    store["dash-group-by"] = "invalid";
    const s = initialState();
    expect(s.groupBy).toBe("none");
  });

  it("defaults sortMode to default", () => {
    expect(state.sortMode).toBe("default");
    expect(state.statusChangedAt).toEqual({});
  });

  it("reads sortMode preference from localStorage", () => {
    store["dash-sort"] = "status_changed";
    const s = initialState();
    expect(s.sortMode).toBe("status_changed");
  });

  it("ignores invalid sortMode in localStorage", () => {
    store["dash-sort"] = "bogus";
    const s = initialState();
    expect(s.sortMode).toBe("default");
  });

  it("reads statusChangedAt from localStorage, dropping non-numeric values", () => {
    store["dash-status-changed"] = JSON.stringify({ a: 123, b: "nope", c: 456 });
    const s = initialState();
    expect(s.statusChangedAt).toEqual({ a: 123, c: 456 });
  });
});

describe("appReducer", () => {
  it("SET_TAB changes current tab", () => {
    const next = appReducer(state, { type: "SET_TAB", tab: "timeline" });
    expect(next.currentTab).toBe("timeline");
  });

  it("SET_VIEW changes view", () => {
    const next = appReducer(state, { type: "SET_VIEW", view: "list" });
    expect(next.currentView).toBe("list");
  });

  it("SET_SORT_MODE changes sort mode", () => {
    const next = appReducer(state, { type: "SET_SORT_MODE", sortMode: "status_changed" });
    expect(next.sortMode).toBe("status_changed");
  });

  it("RECORD_STATUS_CHANGES merges changes and prunes absent sessions", () => {
    state = { ...state, statusChangedAt: { old: 1, keep: 2 } };
    const next = appReducer(state, {
      type: "RECORD_STATUS_CHANGES",
      changes: { keep: 99, fresh: 50 },
      presentIds: ["keep", "fresh"],
    });
    // "old" pruned (not present), "keep" updated, "fresh" added
    expect(next.statusChangedAt).toEqual({ keep: 99, fresh: 50 });
  });

  it("SET_SEARCH updates filter", () => {
    const next = appReducer(state, { type: "SET_SEARCH", filter: "auth" });
    expect(next.searchFilter).toBe("auth");
  });

  it("TOGGLE_EXPAND adds session ID, clears previous", () => {
    let next = appReducer(state, { type: "TOGGLE_EXPAND", sessionId: "a" });
    expect(next.expandedSessionIds.has("a")).toBe(true);
    next = appReducer(next, { type: "TOGGLE_EXPAND", sessionId: "b" });
    expect(next.expandedSessionIds.has("a")).toBe(false);
    expect(next.expandedSessionIds.has("b")).toBe(true);
  });

  it("TOGGLE_EXPAND collapses when same ID toggled", () => {
    let next = appReducer(state, { type: "TOGGLE_EXPAND", sessionId: "a" });
    next = appReducer(next, { type: "TOGGLE_EXPAND", sessionId: "a" });
    expect(next.expandedSessionIds.size).toBe(0);
  });

  it("TOGGLE_GROUP toggles group collapsed state", () => {
    let next = appReducer(state, { type: "TOGGLE_GROUP", groupId: "g1" });
    expect(next.collapsedGroups.has("g1")).toBe(true);
    next = appReducer(next, { type: "TOGGLE_GROUP", groupId: "g1" });
    expect(next.collapsedGroups.has("g1")).toBe(false);
  });

  it("TOGGLE_STAR toggles starred sessions", () => {
    let next = appReducer(state, { type: "TOGGLE_STAR", sessionId: "s1" });
    expect(next.starredSessions.has("s1")).toBe(true);

    next = appReducer(next, { type: "TOGGLE_STAR", sessionId: "s1" });
    expect(next.starredSessions.has("s1")).toBe(false);
  });

  it("RECORD_FETCH_SUCCESS resets failure counter", () => {
    state = { ...state, consecutiveFailures: 5 };
    const next = appReducer(state, { type: "RECORD_FETCH_SUCCESS" });
    expect(next.consecutiveFailures).toBe(0);
  });

  it("RECORD_FETCH_FAILURE increments failure counter", () => {
    const next = appReducer(state, { type: "RECORD_FETCH_FAILURE" });
    expect(next.consecutiveFailures).toBe(1);
  });

  it("SET_SERVER_PID stores pid", () => {
    const next = appReducer(state, { type: "SET_SERVER_PID", pid: 9999 });
    expect(next.serverPid).toBe(9999);
  });

  it("SET_GROUP_BY changes groupBy", () => {
    const next = appReducer(state, { type: "SET_GROUP_BY", groupBy: "project" });
    expect(next.groupBy).toBe("project");
  });

  it("SET_GROUP_BY to machine", () => {
    const next = appReducer(state, { type: "SET_GROUP_BY", groupBy: "machine" });
    expect(next.groupBy).toBe("machine");
  });

  it("SET_GROUP_BY back to none", () => {
    let next = appReducer(state, { type: "SET_GROUP_BY", groupBy: "project" });
    next = appReducer(next, { type: "SET_GROUP_BY", groupBy: "none" });
    expect(next.groupBy).toBe("none");
  });

  it("SET_UPDATING sets updating and target", () => {
    const next = appReducer(state, {
      type: "SET_UPDATING",
      updating: true,
      target: "2.1.0",
    });
    expect(next.updating).toBe(true);
    expect(next.updateTarget).toBe("2.1.0");
  });

  it("SET_UPDATING clears target when updating is false", () => {
    let next = appReducer(state, {
      type: "SET_UPDATING",
      updating: true,
      target: "2.1.0",
    });
    next = appReducer(next, { type: "SET_UPDATING", updating: false });
    expect(next.updating).toBe(false);
    expect(next.updateTarget).toBeNull();
  });
});

describe("isDisconnected()", () => {
  it("returns false when failures < 2", () => {
    expect(isDisconnected({ ...state, consecutiveFailures: 1 })).toBe(false);
  });

  it("returns true when failures >= 2", () => {
    expect(isDisconnected({ ...state, consecutiveFailures: 2 })).toBe(true);
    expect(isDisconnected({ ...state, consecutiveFailures: 5 })).toBe(true);
  });
});
