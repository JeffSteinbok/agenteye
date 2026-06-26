import { useEffect, useRef } from "react";
import { fetchSessions, fetchProcesses, fetchRemoteSessions } from "../api";
import { BACKGROUND_POLL_MS, PROCESS_POLL_MS, SESSION_POLL_MS } from "../constants";
import { useAppState, useAppDispatch } from "../state";
import type { ProcessMap } from "../types";

/**
 * Polling driver for sessions and process state.
 *
 * Polling is Page Visibility-aware so latency is minimised when the user is
 * actually looking at the dashboard, while resources are conserved otherwise:
 *   - Visible: fast process-state poll (PROCESS_POLL_MS) + periodic full
 *     session refetch (SESSION_POLL_MS). Becoming visible triggers an immediate
 *     catch-up fetch so there is no wait for the next tick.
 *   - Hidden: the fast/full polls are paused. A single slow poll
 *     (BACKGROUND_POLL_MS) is kept alive ONLY when desktop notifications are
 *     enabled, so state-transition alerts still fire while backgrounded.
 *     With notifications off, polling stops entirely.
 */
export function useSessions() {
  const dispatch = useAppDispatch();
  const { notificationsEnabled, sessions, processes } = useAppState();
  const prevProcesses = useRef<ProcessMap>({});
  const sessionsRef = useRef(sessions);
  const notifRef = useRef(notificationsEnabled);
  sessionsRef.current = sessions;
  notifRef.current = notificationsEnabled;

  // Full session + process + remote fetch
  const fetchAll = async () => {
    try {
      const [sess, procs] = await Promise.all([
        fetchSessions(),
        fetchProcesses(),
      ]);
      dispatch({ type: "SET_SESSIONS", sessions: sess });
      checkTransitions(prevProcesses.current, procs);
      prevProcesses.current = procs;
      dispatch({ type: "SET_PROCESSES", processes: procs });
      dispatch({ type: "RECORD_FETCH_SUCCESS" });
    } catch {
      dispatch({ type: "RECORD_FETCH_FAILURE" });
    }

    // Remote sessions — fire-and-forget, don't block main poll
    fetchRemoteSessions()
      .then((remote) => dispatch({ type: "SET_REMOTE_SESSIONS", sessions: remote }))
      .catch(() => {});
  };

  // Process-only fetch (fast poll)
  const fetchProcs = async () => {
    try {
      const procs = await fetchProcesses();
      checkTransitions(prevProcesses.current, procs);
      prevProcesses.current = procs;
      dispatch({ type: "SET_PROCESSES", processes: procs });
      dispatch({ type: "RECORD_FETCH_SUCCESS" });
    } catch {
      dispatch({ type: "RECORD_FETCH_FAILURE" });
    }
  };

  // Desktop notification on state transition
  const checkTransitions = (oldP: ProcessMap, newP: ProcessMap) => {
    if (!notifRef.current) return;
    for (const [sid, info] of Object.entries(newP)) {
      const oldState = oldP[sid]?.state ?? null;
      if (!oldState) continue;
      if (
        info.state !== oldState &&
        (info.state === "waiting" || info.state === "idle")
      ) {
        const session = sessionsRef.current.find((s) => s.id === sid);
        const title = session
          ? session.intent || session.summary || "Copilot Session"
          : "Copilot Session";
        const body =
          info.waiting_context ||
          (info.state === "waiting"
            ? "Session is waiting for your input"
            : "Session is done and ready for next task");
        try {
          // Use native notification in pywebview, browser Notification otherwise
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const pywebview = (window as any).pywebview;
          if (pywebview?.api?.send_notification) {
            pywebview.api.send_notification(title, body);
          } else {
            new Notification(title, { body, tag: "copilot-" + sid });
          }
        } catch {
          // Notification permission may have been revoked
        }
      }
    }
  };

  useEffect(() => {
    let fastTimer: ReturnType<typeof setInterval> | null = null;
    let fullTimer: ReturnType<typeof setInterval> | null = null;
    let bgTimer: ReturnType<typeof setInterval> | null = null;

    const stop = (t: ReturnType<typeof setInterval> | null) => {
      if (t !== null) clearInterval(t);
    };

    // Visible: snappy state poll + periodic full refresh.
    const startForeground = () => {
      stop(bgTimer);
      bgTimer = null;
      if (fastTimer === null) fastTimer = setInterval(fetchProcs, PROCESS_POLL_MS);
      if (fullTimer === null) fullTimer = setInterval(fetchAll, SESSION_POLL_MS);
    };

    // Hidden: pause heavy polling; keep a slow poll only to drive desktop
    // notifications, and only when they are enabled.
    const startBackground = () => {
      stop(fastTimer);
      fastTimer = null;
      stop(fullTimer);
      fullTimer = null;
      if (notifRef.current) {
        if (bgTimer === null) bgTimer = setInterval(fetchProcs, BACKGROUND_POLL_MS);
      } else {
        stop(bgTimer);
        bgTimer = null;
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === "visible") {
        fetchAll(); // instant catch-up on focus
        startForeground();
      } else {
        startBackground();
      }
    };

    handleVisibility(); // kick off based on current visibility
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      stop(fastTimer);
      stop(fullTimer);
      stop(bgTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { processes, sessions };
}
