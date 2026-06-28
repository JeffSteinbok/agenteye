/**
 * One-time deprecation notice shown on startup.
 *
 * This distribution (`ghcp-cli-dashboard` / "Copilot Dashboard") has been
 * renamed and moved to **Agent Eye** (`agenteye-app` on PyPI). The dialog
 * points users at the new package and remembers dismissal in localStorage so
 * it only nags once.
 */

import { useEffect, useCallback, useState } from "react";

const DISMISS_KEY = "agenteye-deprecation-dismissed";

export default function DeprecationModal() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    try {
      if (localStorage.getItem(DISMISS_KEY) !== "1") setOpen(true);
    } catch {
      setOpen(true);
    }
  }, []);

  const dismiss = useCallback(() => {
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* ignore storage errors */
    }
    setOpen(false);
  }, []);

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    },
    [dismiss],
  );

  useEffect(() => {
    if (!open) return;
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, handleKey]);

  if (!open) return null;

  return (
    <div
      className="confirm-modal-overlay open"
      onClick={(e) => {
        if (e.target === e.currentTarget) dismiss();
      }}
    >
      <div className="confirm-modal deprecation-modal">
        <img src="/static/logo.png" alt="Agent Eye" className="deprecation-logo" />
        <div className="confirm-modal-header">
          <h2>This project is now Agent Eye</h2>
        </div>
        <p className="confirm-modal-message">
          <strong>Copilot Dashboard</strong> has been renamed to{" "}
          <strong>Agent Eye</strong> and now ships as a new package. This old
          package (<code>ghcp-cli-dashboard</code>) will no longer be updated.
          <br />
          <br />
          Please switch to the new package to keep getting updates:
          <br />
          <code className="deprecation-cmd">
            pip uninstall ghcp-cli-dashboard
            <br />
            pip install agenteye-app
          </code>
        </p>
        <div className="confirm-modal-actions">
          <a
            className="confirm-btn-primary"
            href="https://pypi.org/project/agenteye-app/"
            target="_blank"
            rel="noreferrer"
            onClick={dismiss}
          >
            Get Agent Eye
          </a>
          <button className="confirm-btn-secondary" onClick={dismiss}>
            Dismiss
          </button>
        </div>
      </div>
    </div>
  );
}
