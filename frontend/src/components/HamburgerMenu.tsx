/**
 * Hamburger menu (☰) — dropdown in the header-right area, next to
 * the timestamp.
 *
 * Contains:
 *   - "Start on login" toggle (hidden when platform doesn't support it)
 *   - "Remote sync" toggle (enables/disables OneDrive sync)
 *   - Divider
 *   - "About" opens a help modal (restored from the old "What is this?" popup)
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchServerInfo } from "../api";
import { useAutostart, useSettings } from "../hooks";
import type { ServerInfo } from "../types";

export default function HamburgerMenu() {
  const [open, setOpen] = useState(false);
  const [showAbout, setShowAbout] = useState(false);
  const [serverInfo, setServerInfo] = useState<ServerInfo | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const autostart = useAutostart();
  const { settings, loading: settingsLoading, setSyncEnabled, setLogLevel } = useSettings();

  const toggle = useCallback(() => setOpen((prev) => !prev), []);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  // Fetch server info when About dialog opens
  useEffect(() => {
    if (!showAbout) return;
    fetchServerInfo()
      .then(setServerInfo)
      .catch(() => {});
  }, [showAbout]);

  return (
    <>
      <div className="hamburger-wrapper" ref={menuRef}>
        <button
          className="hamburger-btn"
          onClick={toggle}
          title="Settings"
          aria-label="Open settings menu"
          aria-expanded={open}
        >
          ☰
        </button>

        {open && (
          <div className="hamburger-dropdown" role="menu">
            {/* Autostart toggle — only shown when platform supports it */}
            {autostart.supported && (
              <label className="hamburger-item hamburger-toggle" role="menuitem">
                <span>Start on login</span>
                <input
                  type="checkbox"
                  checked={autostart.enabled}
                  disabled={autostart.toggling}
                  onChange={(e) => autostart.toggle(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            )}

            {/* Remote sync toggle */}
            {!settingsLoading && (
              <label className="hamburger-item hamburger-toggle" role="menuitem">
                <span>Remote sync</span>
                <input
                  type="checkbox"
                  checked={settings.sync_enabled}
                  onChange={(e) => setSyncEnabled(e.target.checked)}
                />
                <span className="toggle-slider" />
              </label>
            )}

            {/* Log level selector */}
            {!settingsLoading && (
              <label className="hamburger-item hamburger-select" role="menuitem">
                <span>Log level</span>
                <select
                  value={settings.log_level}
                  onChange={(e) => setLogLevel(e.target.value)}
                >
                  <option value="DEBUG">DEBUG</option>
                  <option value="INFO">INFO</option>
                  <option value="WARNING">WARNING</option>
                  <option value="ERROR">ERROR</option>
                </select>
              </label>
            )}

            <div className="hamburger-divider" />

            {/* About — opens help modal */}
            <button
              className="hamburger-item"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                setShowAbout(true);
              }}
            >
              About
            </button>
          </div>
        )}
      </div>

      {/* About modal — restored from the legacy "What is this?" popup */}
      {showAbout && (
        <div
          className="modal-overlay open"
          onClick={(e) => {
            if (e.target === e.currentTarget) setShowAbout(false);
          }}
        >
          <div className="modal">
            <h2 className="about-title">
              <img src="/static/logo.png" alt="" className="about-logo" />
              Agent Eye
            </h2>
            <p>
              A local dashboard that monitors all your GitHub Copilot CLI and
              Claude Code sessions in real-time.
            </p>
            <p>
              <a
                href="https://github.com/JeffSteinbok/agenteye"
                target="_blank"
                rel="noreferrer"
                style={{ color: "var(--accent)", textDecoration: "underline" }}
              >
                📖 View full documentation on GitHub
              </a>
            </p>
            <p>
              <strong>Features:</strong>
            </p>
            <ul>
              <li>
                <strong>Claude Code support</strong> — automatically discovers
                Claude Code sessions alongside Copilot sessions.
              </li>
              <li>
                <strong>Session states</strong> —{" "}
                <span style={{ color: "var(--green)" }}>● Working/Thinking</span>,{" "}
                <span style={{ color: "var(--yellow)" }}>● Waiting</span> (needs
                input),{" "}
                <span style={{ color: "var(--accent)" }}>● Idle</span> (ready
                for next task).
              </li>
              <li>
                <strong>Cross-machine sync</strong> — see active sessions from
                all your machines via OneDrive or any cloud-synced folder.
              </li>
              <li>
                <strong>Desktop notifications</strong> — get alerts when sessions
                change state so you don't have to watch the dashboard.
              </li>
              <li>
                <strong>Focus window</strong> — bring an active session's
                terminal to the foreground with one click.
              </li>
              <li>
                <strong>Restart commands</strong> — copy-pasteable resume
                commands for every session.
              </li>
            </ul>
            {serverInfo?.log_file && (
              <p style={{ fontSize: "0.85em", opacity: 0.8 }}>
                📄 <strong>Log file:</strong>{" "}
                <code style={{ wordBreak: "break-all" }}>{serverInfo.log_file}</code>
                <br />
                Log level: <strong>{serverInfo.log_level}</strong> · Change in
                Settings menu above
              </p>
            )}
            <button
              className="close-btn"
              onClick={() => setShowAbout(false)}
            >
              Got it
            </button>
          </div>
        </div>
      )}
    </>
  );
}
