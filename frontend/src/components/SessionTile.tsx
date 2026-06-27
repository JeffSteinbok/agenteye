/**
 * Session tile — compact card for the grid/tile view.
 */

import type { Session, ProcessInfo } from "../types";
import { COPY_FEEDBACK_MS } from "../constants";
import { TILE_STATE_CLASS } from "../utils";
import { useAppState, useAppDispatch } from "../state";
import { focusSession, killSession } from "../api";
import { useDismissSession } from "../hooks/useDismissSession";
import { showToast } from "./Toast";
import BgTaskPopover from "./BgTaskPopover";

interface SessionTileProps {
  session: Session;
  processInfo: ProcessInfo | undefined;
  onOpenDetail: (id: string, title: string) => void;
}

export default function SessionTile({ session: s, processInfo, onOpenDetail }: SessionTileProps) {
  const { starredSessions } = useAppState();
  const dispatch = useAppDispatch();
  const dismiss = useDismissSession();

  const isRunning = !!processInfo;
  const isRemote = !!s.machine_name;
  const state = isRunning ? (processInfo!.state || "unknown") : (isRemote && s.state ? s.state : "");
  const isWaiting = (isRunning || isRemote) && state === "waiting";
  const isStarred = starredSessions.has(s.id);
  const tileClass = (isRunning || isRemote) ? (TILE_STATE_CLASS[state] || "") : "";

  const displayTitle = (isRunning || isRemote) && s.intent ? s.intent : s.summary || "(Untitled)";
  const handleClick = () => {
    if (!isRemote) onOpenDetail(s.id, displayTitle);
  };
  const stop = (e: React.MouseEvent) => e.stopPropagation();

  const handleCopy = (e: React.MouseEvent) => {
    stop(e);
    navigator.clipboard.writeText(s.restart_cmd).catch(() => {});
    const btn = e.currentTarget;
    const orig = btn.textContent;
    btn.textContent = "✓";
    setTimeout(() => { btn.textContent = orig; }, COPY_FEEDBACK_MS);
  };

  const handleCopyId = (e: React.MouseEvent) => {
    stop(e);
    navigator.clipboard.writeText(s.id).catch(() => {});
    const btn = e.currentTarget;
    btn.textContent = "✓";
    setTimeout(() => { btn.textContent = "🪪"; }, COPY_FEEDBACK_MS);
  };

  const handleDismiss = (e: React.MouseEvent) => {
    stop(e);
    dismiss(s.id);
  };

  return (
    <div className={`tile-card ${tileClass}`} data-source={s.source || "copilot"} onClick={handleClick}>
      <div className="tile-subtitle" style={{ fontSize: 11, opacity: 0.7 }}>
        started {s.created_ago}
      </div>

      {/* Title row */}
      <div className="tile-top">
        {(isRunning || isRemote) && (
          <span
            className={`live-dot ${isWaiting ? "waiting" : state === "idle" ? "idle" : ""}`}
            style={{ flexShrink: 0 }}
          />
        )}
        <div
          className="tile-title"
          data-tip={
            (isRunning || isRemote) && s.intent
              ? `Intent: ${s.intent}`
              : `Session: ${s.summary || "(Untitled session)"}`
          }
        >
          {(isRunning || isRemote) && s.intent ? `🤖 ${s.intent}` : s.summary || "(Untitled session)"}
        </div>
        {isRunning && processInfo?.window_title && processInfo.window_title !== s.summary && !(s.intent && processInfo.window_title.includes(s.intent)) && (
          <div className="tile-subtitle" style={{ opacity: 0.7 }} data-tip={`Window: ${processInfo.window_title}`}>
            🪟 {processInfo.window_title}
          </div>
        )}
        {isRunning && processInfo!.yolo && (
          <span className="badge badge-yolo" style={{ flexShrink: 0 }} data-tip="YOLO mode enabled">🔥</span>
        )}
      </div>

      {/* Branch */}
      {s.branch && (
        <div className="tile-subtitle">
          <span
            className="branch-badge"
            data-tip={`Repository/Branch: ${s.repository ? s.repository + "/" : ""}${s.branch}`}
          >
            ⎇ {s.repository ? s.repository + "/" : ""}{s.branch}
          </span>
        </div>
      )}

      {/* Recent activity */}
      {s.recent_activity && (
        <div className="tile-subtitle" style={{ color: "var(--accent)" }} data-tip={`Latest checkpoint: ${s.recent_activity}`}>
          {s.recent_activity}
        </div>
      )}

      {/* Waiting context */}
      {isWaiting && processInfo!.waiting_context && (
        <div className="tile-subtitle" style={{ color: "var(--yellow)" }} data-tip={`Waiting for: ${processInfo!.waiting_context}`}>
          {processInfo!.waiting_context.substring(0, 80)}
          {processInfo!.waiting_context.length > 80 ? "..." : ""}
        </div>
      )}

      {/* Badge row */}
      <div className="tile-meta">
        {/* State is already shown by the live-dot — no badge needed here */}
        {isRunning && processInfo!.bg_tasks > 0 && (
          <BgTaskPopover
            count={processInfo!.bg_tasks}
            tasks={processInfo!.bg_task_list || []}
            label={`⚙️ ${processInfo!.bg_tasks} bg`}
          />
        )}
        <span className="badge badge-turns">💬 {s.turn_count}</span>
        {s.checkpoint_count > 0 && (
          <span className="badge badge-cp" data-tip={`${s.checkpoint_count} checkpoint${s.checkpoint_count !== 1 ? "s" : ""}`}>
            🏁 {s.checkpoint_count}
          </span>
        )}
        {s.mcp_servers?.map((m) => (
          <span key={m} className="badge badge-mcp">🔌 {m}</span>
        ))}
        {isRunning && !isRemote && (
          <span className="badge badge-focus" onClick={(e) => { stop(e); focusSession(s.id).then((r) => { if (!r.success) showToast(r.message || "Could not focus window", "error"); }).catch(() => showToast("Focus request failed", "error")); }} data-tip="Focus terminal window">
            👁️
          </span>
        )}
        {!isRemote && <span className="badge badge-focus" onClick={handleCopy} data-tip="Copy resume command">📋</span>}
        <span className="badge badge-focus" onClick={handleCopyId} data-tip="Copy session ID">🪪</span>
        {!isRemote && (
          <span className="badge badge-focus" onClick={handleDismiss} data-tip="Hide session from dashboard">🙈</span>
        )}
        <span
          className="badge badge-focus star-btn"
          onClick={(e) => { stop(e); dispatch({ type: "TOGGLE_STAR", sessionId: s.id }); }}
          data-tip={isStarred ? "Unpin session" : "Pin session"}
        >
          {isStarred ? "⭐" : "☆"}
        </span>
        {isRemote && (
          <span className="badge badge-mcp" data-tip={`Remote machine: ${s.machine_name}`}>
            🖥️ {s.machine_name}
          </span>
        )}
      </div>

      {/* PID + kill button */}
      {isRunning && !isRemote && processInfo!.pid > 0 && (
        <div className="tile-pid-kill" onClick={stop}>
          PID {processInfo!.pid}{" "}
          <span
            className="tile-kill-x"
            onClick={() => {
              if (confirm(`Kill process PID ${processInfo!.pid}?`)) {
                killSession(s.id).catch(() => {});
              }
            }}
            data-tip="Kill process"
          >
            ✕
          </span>
        </div>
      )}

      {/* Source badge */}
      {s.source === "claude" && (
        <div className="tile-source-badge">
          <span className="badge badge-claude">✦ Claude</span>
        </div>
      )}
    </div>
  );
}
