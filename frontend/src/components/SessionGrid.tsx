/**
 * Session grid — tile view. Renders sessions as compact cards in a CSS grid.
 *
 * Supports optional grouping by project or machine. Starred sessions sort
 * first within each group. Clicking a tile opens the detail modal.
 */

import { useState } from "react";
import type { Session, ProcessMap } from "../types";
import { groupSessionsBy, sortStarredFirst } from "../utils";
import { useAppState, useAppDispatch } from "../state";
import SessionTile from "./SessionTile";
import DetailModal from "./DetailModal";

interface SessionGridProps {
  sessions: Session[];
  processes: ProcessMap;
  isActive: boolean;
}

export default function SessionGrid({ sessions, processes, isActive }: SessionGridProps) {
  const { starredSessions, groupBy, sortMode, statusChangedAt, collapsedGroups, sessionsLoaded } = useAppState();
  const dispatch = useAppDispatch();
  const [modalSession, setModalSession] = useState<{ id: string; title: string } | null>(null);

  if (sessions.length === 0) {
    if (!sessionsLoaded) {
      return (
        <div className="loading">
          <div className="spinner" aria-hidden="true" />
          <div>Loading sessions…</div>
        </div>
      );
    }
    return (
      <div className="empty">
        {isActive ? "No active sessions detected." : "No previous sessions."}
      </div>
    );
  }

  const groups = groupSessionsBy(sessions, groupBy);
  const showGroupHeaders = groupBy !== "none";

  return (
    <>
      {groups.map(([groupName, items]) => {
        const sorted = sortStarredFirst(items, starredSessions, sortMode, statusChangedAt);
        const gid = `tile-${groupName}`.replace(/[^a-zA-Z0-9]/g, "_");
        const isCollapsed = collapsedGroups.has(gid);

        return (
          <div key={gid}>
            {showGroupHeaders && (
              <div
                className={`group-header ${isCollapsed ? "collapsed" : ""}`}
                onClick={() => dispatch({ type: "TOGGLE_GROUP", groupId: gid })}
              >
                <span className="arrow">▼</span>
                {groupName}
                <span className="group-count">({items.length})</span>
              </div>
            )}
            {!isCollapsed && (
              <div className="tile-grid">
                {sorted.map((s) => (
                  <SessionTile
                    key={s.id}
                    session={s}
                    processInfo={processes[s.id]}
                    onOpenDetail={(id, title) => setModalSession({ id, title })}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}

      {modalSession && (
        <DetailModal
          sessionId={modalSession.id}
          title={modalSession.title}
          processes={processes}
          sessions={sessions}
          onClose={() => setModalSession(null)}
        />
      )}
    </>
  );
}
