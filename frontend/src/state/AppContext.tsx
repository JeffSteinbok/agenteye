/**
 * Global application state management using React Context + useReducer.
 *
 * Centralises all application state (sessions, processes, current tab,
 * expanded IDs, etc.) into a single typed state tree managed by a reducer.
 * The reducer is a pure function — easy to test without rendering components.
 *
 * Usage:
 *   const state = useAppState();
 *   const dispatch = useAppDispatch();
 *   dispatch({ type: "SET_TAB", tab: "timeline" });
 */

import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";
import {
  DISCONNECT_THRESHOLD,
  STORAGE_KEY_GROUP_BY,
  STORAGE_KEY_SORT,
  STORAGE_KEY_STARRED,
  STORAGE_KEY_STATUS_CHANGED,
  STORAGE_KEY_VIEW,
  STORAGE_KEY_WIDGETS_COLLAPSED,
} from "../constants";
import type { Session, ProcessMap } from "../types";

// ── State shape ──────────────────────────────────────────────────────────────

export type Tab = "active" | "previous" | "timeline" | "files";
export type View = "tile" | "list";
export type GroupBy = "none" | "project" | "machine";
export type SortMode = "default" | "status_changed";

const VALID_VIEWS: View[] = ["tile", "list"];
const VALID_GROUP_BY: GroupBy[] = ["none", "project", "machine"];
const VALID_SORTS: SortMode[] = ["default", "status_changed"];

function safeParseStarred(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_STARRED);
    if (!raw) return new Set();
    const arr = JSON.parse(raw);
    if (Array.isArray(arr)) return new Set(arr as string[]);
  } catch { /* corrupt localStorage */ }
  return new Set();
}

function safeParseStatusChanged(): Record<string, number> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_STATUS_CHANGED);
    if (!raw) return {};
    const obj = JSON.parse(raw);
    if (obj && typeof obj === "object" && !Array.isArray(obj)) {
      const out: Record<string, number> = {};
      for (const [k, v] of Object.entries(obj)) {
        if (typeof v === "number" && Number.isFinite(v)) out[k] = v;
      }
      return out;
    }
  } catch { /* corrupt localStorage */ }
  return {};
}

export interface AppState {
  sessions: Session[];
  remoteSessions: Session[];
  processes: ProcessMap;
  currentTab: Tab;
  currentView: View;
  groupBy: GroupBy;
  sortMode: SortMode;
  /** Epoch ms a running session most recently entered `waiting` or `idle`. */
  statusChangedAt: Record<string, number>;
  searchFilter: string;
  expandedSessionIds: Set<string>;
  collapsedGroups: Set<string>;
  starredSessions: Set<string>;
  widgetsCollapsed: boolean;
  notificationsEnabled: boolean;
  consecutiveFailures: number;
  lastFetchedAt: number | null;
  /**
   * True once the first full session list has been fetched. Distinct from
   * `lastFetchedAt`, which is also set by the fast process-only poll — using
   * that for the initial loading guard caused a flash of the empty state when
   * the process poll won the race against the slower first session fetch.
   */
  sessionsLoaded: boolean;
  serverPid: number | null;
  /** True while a version update is in progress. */
  updating: boolean;
  /** Target version string during an update, e.g. "2.1.0". */
  updateTarget: string | null;
}

export function initialState(): AppState {
  const rawView = localStorage.getItem(STORAGE_KEY_VIEW) as View | null;
  const currentView: View = rawView && VALID_VIEWS.includes(rawView) ? rawView : "tile";
  const rawGroupBy = localStorage.getItem(STORAGE_KEY_GROUP_BY) as GroupBy | null;
  const groupBy: GroupBy = rawGroupBy && VALID_GROUP_BY.includes(rawGroupBy) ? rawGroupBy : "none";
  const rawSort = localStorage.getItem(STORAGE_KEY_SORT) as SortMode | null;
  const sortMode: SortMode = rawSort && VALID_SORTS.includes(rawSort) ? rawSort : "default";
  return {
    sessions: [],
    remoteSessions: [],
    processes: {},
    currentTab: "active",
    currentView,
    groupBy,
    sortMode,
    statusChangedAt: safeParseStatusChanged(),
    searchFilter: "",
    expandedSessionIds: new Set(),
    collapsedGroups: new Set(),
    starredSessions: safeParseStarred(),
    widgetsCollapsed: localStorage.getItem(STORAGE_KEY_WIDGETS_COLLAPSED) === "true",
    notificationsEnabled:
      typeof Notification !== "undefined" &&
      Notification.permission === "granted",
    consecutiveFailures: 0,
    lastFetchedAt: null,
    sessionsLoaded: false,
    serverPid: null,
    updating: false,
    updateTarget: null,
  };
}

// ── Actions ──────────────────────────────────────────────────────────────────

export type Action =
  | { type: "SET_SESSIONS"; sessions: Session[] }
  | { type: "SET_REMOTE_SESSIONS"; sessions: Session[] }
  | { type: "SET_PROCESSES"; processes: ProcessMap }
  | { type: "SET_TAB"; tab: Tab }
  | { type: "SET_VIEW"; view: View }
  | { type: "SET_GROUP_BY"; groupBy: GroupBy }
  | { type: "SET_SORT_MODE"; sortMode: SortMode }
  | { type: "RECORD_STATUS_CHANGES"; changes: Record<string, number>; presentIds: string[] }
  | { type: "SET_SEARCH"; filter: string }
  | { type: "TOGGLE_EXPAND"; sessionId: string }
  | { type: "TOGGLE_GROUP"; groupId: string }
  | { type: "TOGGLE_STAR"; sessionId: string }
  | { type: "TOGGLE_WIDGETS_COLLAPSED" }
  | { type: "SET_NOTIFICATIONS"; enabled: boolean }
  | { type: "RECORD_FETCH_SUCCESS" }
  | { type: "RECORD_FETCH_FAILURE" }
  | { type: "SET_SERVER_PID"; pid: number }
  | { type: "SET_UPDATING"; updating: boolean; target?: string | null };

// ── Reducer ──────────────────────────────────────────────────────────────────

export function appReducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "SET_SESSIONS":
      return { ...state, sessions: action.sessions, sessionsLoaded: true };

    case "SET_REMOTE_SESSIONS":
      return { ...state, remoteSessions: action.sessions };

    case "SET_PROCESSES":
      return { ...state, processes: action.processes };

    case "SET_TAB":
      return { ...state, currentTab: action.tab };

    case "SET_VIEW":
      return { ...state, currentView: action.view };

    case "SET_GROUP_BY":
      return { ...state, groupBy: action.groupBy };

    case "SET_SORT_MODE":
      return { ...state, sortMode: action.sortMode };

    case "RECORD_STATUS_CHANGES": {
      const present = new Set(action.presentIds);
      const next: Record<string, number> = {};
      // Keep only currently-present (running) sessions to stay bounded.
      for (const [id, ts] of Object.entries(state.statusChangedAt)) {
        if (present.has(id)) next[id] = ts;
      }
      for (const [id, ts] of Object.entries(action.changes)) {
        next[id] = ts;
      }
      return { ...state, statusChangedAt: next };
    }

    case "SET_SEARCH":
      return { ...state, searchFilter: action.filter };

    case "TOGGLE_EXPAND": {
      const next = new Set(state.expandedSessionIds);
      if (next.has(action.sessionId)) {
        next.delete(action.sessionId);
      } else {
        next.clear();
        next.add(action.sessionId);
      }
      return { ...state, expandedSessionIds: next };
    }

    case "TOGGLE_GROUP": {
      const next = new Set(state.collapsedGroups);
      if (next.has(action.groupId)) next.delete(action.groupId);
      else next.add(action.groupId);
      return { ...state, collapsedGroups: next };
    }

    case "TOGGLE_STAR": {
      const next = new Set(state.starredSessions);
      if (next.has(action.sessionId)) next.delete(action.sessionId);
      else next.add(action.sessionId);
      return { ...state, starredSessions: next };
    }

    case "TOGGLE_WIDGETS_COLLAPSED":
      return { ...state, widgetsCollapsed: !state.widgetsCollapsed };

    case "SET_NOTIFICATIONS":
      return { ...state, notificationsEnabled: action.enabled };

    case "RECORD_FETCH_SUCCESS":
      return { ...state, consecutiveFailures: 0, lastFetchedAt: Date.now() };

    case "RECORD_FETCH_FAILURE":
      return {
        ...state,
        consecutiveFailures: state.consecutiveFailures + 1,
      };

    case "SET_SERVER_PID":
      return { ...state, serverPid: action.pid };

    case "SET_UPDATING":
      return {
        ...state,
        updating: action.updating,
        updateTarget: action.target ?? null,
      };

    default:
      return state;
  }
}

// ── Selectors ────────────────────────────────────────────────────────────────

export function isDisconnected(state: AppState): boolean {
  return state.consecutiveFailures >= DISCONNECT_THRESHOLD;
}

// ── Context ──────────────────────────────────────────────────────────────────

const AppStateContext = createContext<AppState | null>(null);
const AppDispatchContext = createContext<Dispatch<Action> | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, undefined, initialState);

  // Sync localStorage outside the reducer (pure reducer, side effects here)
  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_VIEW, state.currentView);
  }, [state.currentView]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_GROUP_BY, state.groupBy);
  }, [state.groupBy]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_SORT, state.sortMode);
  }, [state.sortMode]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_STATUS_CHANGED, JSON.stringify(state.statusChangedAt));
  }, [state.statusChangedAt]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_STARRED, JSON.stringify([...state.starredSessions]));
  }, [state.starredSessions]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY_WIDGETS_COLLAPSED, String(state.widgetsCollapsed));
  }, [state.widgetsCollapsed]);

  return (
    <AppStateContext.Provider value={state}>
      <AppDispatchContext.Provider value={dispatch}>
        {children}
      </AppDispatchContext.Provider>
    </AppStateContext.Provider>
  );
}

export function useAppState(): AppState {
  const ctx = useContext(AppStateContext);
  if (!ctx) throw new Error("useAppState must be used within AppProvider");
  return ctx;
}

export function useAppDispatch(): Dispatch<Action> {
  const ctx = useContext(AppDispatchContext);
  if (!ctx) throw new Error("useAppDispatch must be used within AppProvider");
  return ctx;
}
