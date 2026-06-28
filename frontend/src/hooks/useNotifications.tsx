import { useCallback, type ReactNode } from "react";
import { useAppState, useAppDispatch } from "../state";

// Check if running in pywebview native app
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const getPyWebView = () => (window as any).pywebview;
const isNativeApp = () => !!getPyWebView()?.api;

export function useNotifications() {
  const { notificationsEnabled } = useAppState();
  const dispatch = useAppDispatch();

  const toggle = useCallback(() => {
    // In native app, notifications are always available via tray
    if (isNativeApp()) {
      const next = !notificationsEnabled;
      dispatch({ type: "SET_NOTIFICATIONS", enabled: next });
      if (next) {
        const api = getPyWebView()?.api;
        api?.send_notification?.("Agent Eye", "Notifications enabled!");
      }
      return;
    }

    // Browser: use standard Notification API
    if (!("Notification" in window)) {
      alert("Desktop notifications not supported in this browser");
      return;
    }
    if (Notification.permission === "granted") {
      const next = !notificationsEnabled;
      dispatch({ type: "SET_NOTIFICATIONS", enabled: next });
      if (next) {
        try { new Notification("Agent Eye", { body: "Notifications enabled!" }); }
        catch { /* permission may have been revoked */ }
      }
      return;
    }
    if (Notification.permission === "denied") return;
    Notification.requestPermission().then((p) => {
      const granted = p === "granted";
      dispatch({ type: "SET_NOTIFICATIONS", enabled: granted });
      if (granted) {
        try { new Notification("Agent Eye", { body: "Notifications enabled!" }); }
        catch { /* permission may have been revoked */ }
      }
    });
  }, [notificationsEnabled, dispatch]);

  const popoverContent = useCallback((): ReactNode => {
    // In native app, simplified popover
    if (isNativeApp()) {
      return notificationsEnabled ? (
        <>
          <div className="pop-title">🔔 Notifications On</div>
          <div className="pop-step">Click to <span>turn off</span> notifications.</div>
        </>
      ) : (
        <>
          <div className="pop-title">🔕 Notifications Off</div>
          <div className="pop-step">Click to <span>turn on</span> notifications.</div>
        </>
      );
    }

    // Browser: show permission-based UI
    if (!("Notification" in window)) {
      return (
        <>
          <div className="pop-title">🚫 Not supported</div>
          <div className="pop-step">Your browser does not support desktop notifications.</div>
        </>
      );
    }
    const p = Notification.permission;
    if (p === "granted") {
      return notificationsEnabled ? (
        <>
          <div className="pop-title">🔔 Notifications On</div>
          <div className="pop-step">Click to <span>turn off</span> notifications.</div>
        </>
      ) : (
        <>
          <div className="pop-title">🔕 Notifications Off</div>
          <div className="pop-step">Click to <span>turn on</span> notifications.</div>
        </>
      );
    }
    if (p === "denied") {
      return (
        <>
          <div className="pop-title">🚫 Notifications blocked</div>
          <div className="pop-step">1. Click the <span>🔒 lock icon</span> in the address bar</div>
          <div className="pop-step">2. Find <span>Notifications</span> → set to <span>Allow</span></div>
          <div className="pop-step">3. Refresh the page and click here again</div>
        </>
      );
    }
    return (
      <>
        <div className="pop-title">🔔 Enable notifications</div>
        <div className="pop-step">Click this button, then look for the</div>
        <div className="pop-step"><span>🔔 bell icon</span> in your address bar → click <span>Allow</span></div>
      </>
    );
  }, [notificationsEnabled]);

  return { notificationsEnabled, toggle, popoverContent };
}
