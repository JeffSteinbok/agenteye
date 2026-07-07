/**
 * Session list view — grouped sessions in a vertical card layout.
 *
 * Groups sessions by project, sorts groups by size, starred first within each.
 */

import type { Session, ProcessMap } from "../types";
import { groupSessionsBy, sortStarredFirst } from "../utils";
import { useAppState, useAppDispatch } from "../state";
import SessionCard from "./SessionCard";

interface SessionListProps {
  sessions: Session[];
  processes: ProcessMap;
  isActive: boolean;
  panelId: string;
}

export default function SessionList({ sessions, processes, isActive, panelId }: SessionListProps) {
  const { collapsedGroups, starredSessions, groupBy, sortMode, statusChangedAt, lastFetchedAt } = useAppState();
  const dispatch = useAppDispatch();

  if (sessions.length === 0) {
    if (isActive && lastFetchedAt === null) {
      return <div className="loading">Loading sessions…</div>;
    }
    return (
      <div className="empty">
        {isActive ? "No active sessions detected." : "No previous sessions."}
      </div>
    );
  }

  const effectiveGroupBy = groupBy === "none" ? "project" : groupBy;
  const groups = groupSessionsBy(sessions, effectiveGroupBy);

  return (
    <>
      {groups.map(([groupName, items]) => {
        const gid = `${panelId}-${groupName}`.replace(/[^a-zA-Z0-9]/g, "_");
        const isCollapsed = collapsedGroups.has(gid);
        const sorted = sortStarredFirst(items, starredSessions, sortMode, statusChangedAt);

        return (
          <div key={gid} className="group">
            <div
              className={`group-header ${isCollapsed ? "collapsed" : ""}`}
              onClick={() => dispatch({ type: "TOGGLE_GROUP", groupId: gid })}
            >
              <span className="arrow">▼</span>
              {groupName}
              <span className="group-count">({items.length})</span>
            </div>
            {!isCollapsed && (
              <div className="group-body">
                {sorted.map((s) => (
                  <SessionCard
                    key={s.id}
                    session={s}
                    processInfo={processes[s.id]}
                  />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
