import { dismissSession } from "../api";
import { useAppDispatch, useAppState } from "../state";
import { showToast } from "../components/Toast";

export function useDismissSession() {
  const { sessions } = useAppState();
  const dispatch = useAppDispatch();

  return (sessionId: string) => {
    if (!confirm("Hide this session from the dashboard?")) return;
    dismissSession(sessionId)
      .then((r) => {
        if (!r.success) {
          showToast(r.message || "Could not hide session", "error");
          return;
        }
        dispatch({ type: "SET_SESSIONS", sessions: sessions.filter((s) => s.id !== sessionId) });
        showToast("Session hidden");
      })
      .catch(() => showToast("Hide request failed", "error"));
  };
}
