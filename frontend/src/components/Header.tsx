/**
 * Header component — logo, title, waiting badge, credits, theme controls,
 * and last-updated timestamp.
 */

import { useState } from "react";
import { useTheme, useVersion } from "../hooks";
import type { Palette } from "../hooks";
import { useAppState, useAppDispatch } from "../state";
import { PALETTE_OPTIONS } from "../constants";
import HamburgerMenu from "./HamburgerMenu";
import ConfirmModal from "./ConfirmModal";

interface HeaderProps {
  /** Version string from the Python package, e.g. "1.2.3". */
  initialVersion: string;
  /** ISO timestamp string for "last updated" display. */
  lastUpdated: string;
  /** Number of sessions currently in "waiting" state. */
  waitingCount: number;
}

export default function Header({
  initialVersion,
  lastUpdated,
  waitingCount,
}: HeaderProps) {
  const { theme, toggleMode, setPalette } = useTheme();
  const { versionInfo, updating, doUpdate } = useVersion(initialVersion);
  const { serverPid, widgetsCollapsed } = useAppState();
  const dispatch = useAppDispatch();
  const [showConfirm, setShowConfirm] = useState(false);

  const showUpdateModal = versionInfo.update_available && !updating;

  return (
    <div className="header">
      <img
        src="/static/logo.png"
        style={{
          height: 60,
          width: "auto",
          marginRight: -6,
          verticalAlign: "middle",
        }}
        alt="Agent Eye"
      />
      <div className="brand">
        <h1>Agent Eye</h1>

        {/* Waiting badge — only shown when sessions are waiting for input */}
        {waitingCount > 0 && (
          <span id="waiting-badge" data-tip="Sessions waiting for input">
            ⏳ {waitingCount} waiting
          </span>
        )}

        <div className="header-credits">
        Created by{" "}
        <strong>
          <a
            href="https://github.com/JeffSteinbok"
            target="_blank"
            rel="noreferrer"
          >
            Jeff Steinbok
          </a>
        </strong>
        &nbsp;&bull;&nbsp;
        <span
          id="version-display"
          data-tip={
            showUpdateModal
              ? `v${versionInfo.latest} available — click to update`
              : "Up to date"
          }
          className={showUpdateModal ? "version-update-available" : ""}
          onClick={
            showUpdateModal
              ? () => setShowConfirm(true)
              : undefined
          }
          style={showUpdateModal ? { cursor: "pointer" } : undefined}
        >
          v{versionInfo.current}
          {updating && " ⏳ Updating…"}
          {showUpdateModal && " ⬆"}
        </span>
      </div>
      </div>

      <div className="header-right">
        <div className="theme-controls">
          <button
            className="theme-btn"
            onClick={() => dispatch({ type: "TOGGLE_WIDGETS_COLLAPSED" })}
            data-tip={widgetsCollapsed ? "Show stats widgets" : "Hide stats widgets"}
          >
            {widgetsCollapsed ? "📊 Show Stats" : "📊 Hide Stats"}
          </button>
          <button
            className="theme-btn"
            onClick={toggleMode}
            data-tip="Toggle light/dark mode"
          >
            {theme.mode === "dark" ? "🌙 Dark" : "☀️ Light"}
          </button>
          <select
            className="palette-select"
            data-tip="Color palette"
            value={theme.palette}
            onChange={(e) => setPalette(e.target.value as Palette)}
          >
            {PALETTE_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <div className="header-meta">
          <span className="refresh-dot" />
          <span id="last-updated">{lastUpdated}</span>
        </div>
        <HamburgerMenu />
      </div>

      {/* Server PID — small fixed footer element */}
      {serverPid && (
        <div
          style={{
            position: "fixed",
            bottom: 8,
            right: 12,
            fontSize: 11,
            opacity: 0.4,
            color: "var(--text2)",
            fontFamily: "monospace",
          }}
          data-tip="Dashboard server process ID"
        >
          server PID {serverPid}
        </div>
      )}

      {showConfirm && (
        <ConfirmModal
          title="Update Available"
          message={`Update from v${versionInfo.current} to v${versionInfo.latest}?`}
          confirmLabel="Update Now"
          cancelLabel="Not Now"
          onConfirm={() => {
            setShowConfirm(false);
            doUpdate();
          }}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}
