/**
 * Hook that checks autostart status and provides toggle functionality
 * for the hamburger menu, plus the one-time prompt popover.
 */

import { useEffect, useState, useCallback } from "react";
import { fetchAutostartStatus, enableAutostart, disableAutostart } from "../api";

const DISMISSED_KEY = "agenteye-autostart-dismissed";

interface AutostartState {
  /** Whether autostart is supported on this platform */
  supported: boolean;
  /** Whether autostart is currently enabled */
  enabled: boolean;
  /** Whether to show the one-time popover prompt */
  showPrompt: boolean;
  /** Request in flight */
  toggling: boolean;
  /** Toggle autostart on or off */
  toggle: (enabled: boolean) => void;
  /** Call to enable autostart (from popover) */
  enable: () => void;
  /** Call to dismiss the popover permanently */
  dismiss: () => void;
}

export function useAutostart(): AutostartState {
  const [supported, setSupported] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    fetchAutostartStatus()
      .then((status) => {
        setSupported(status.supported);
        setEnabled(status.enabled);
        // Show prompt if supported, not enabled, and not previously dismissed
        if (status.supported && !status.enabled && !localStorage.getItem(DISMISSED_KEY)) {
          setShowPrompt(true);
        }
      })
      .catch(() => {});
  }, []);

  const toggle = useCallback((newEnabled: boolean) => {
    setToggling(true);
    const action = newEnabled ? enableAutostart() : disableAutostart();
    action
      .then((res) => {
        if (res.success) {
          setEnabled(newEnabled);
          if (newEnabled) {
            localStorage.setItem(DISMISSED_KEY, "1");
            setShowPrompt(false);
          }
        }
      })
      .catch(() => {})
      .finally(() => setToggling(false));
  }, []);

  const enable = useCallback(() => toggle(true), [toggle]);

  const dismiss = useCallback(() => {
    localStorage.setItem(DISMISSED_KEY, "1");
    setShowPrompt(false);
  }, []);

  return { supported, enabled, showPrompt, toggling, toggle, enable, dismiss };
}
