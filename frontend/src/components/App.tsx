/**
 * Root application component — assembles all sub-components into the full
 * dashboard layout and kicks off data-fetching on mount.
 *
 * Layout: Header → StatsRow → TabBar → SearchBar → TabPanels → Tooltip → Disconnect
 */

import { useEffect, useState, useCallback } from "react";
import { AppProvider, useAppState, useAppDispatch } from "../state";
import type { Tab } from "../state";
import { useSessions } from "../hooks";
import { fetchServerInfo } from "../api";
import { filterSessions, splitActivePrevious } from "../utils";
import Header from "./Header";
import StatsRow from "./StatsRow";
import TabBar from "./TabBar";
import SearchBar from "./SearchBar";
import SessionList from "./SessionList";
import SessionGrid from "./SessionGrid";
import Timeline from "./Timeline";
import FilesTab from "./FilesTab";
import DetailModal from "./DetailModal";
import DisconnectOverlay from "./DisconnectOverlay";
import Tooltip from "./Tooltip";
import AutostartPopover from "./AutostartPopover";
import { ToastContainer } from "./Toast";

/** Version injected at build time — falls back to "dev" during development. */
const INITIAL_VERSION = "dev";

function Dashboard() {
  const state = useAppState();
  const dispatch = useAppDispatch();
  const { sessions, remoteSessions, processes, currentTab, currentView, searchFilter, widgetsCollapsed } = state;

  // Start polling
  useSessions();

  // Fetch server PID on mount
  useEffect(() => {
    fetchServerInfo()
      .then((d) => dispatch({ type: "SET_SERVER_PID", pid: d.pid }))
      .catch(() => {});
  }, [dispatch]);

  // Handle URL hash on mount (e.g. #timeline)
  useEffect(() => {
    const validTabs: Tab[] = ["active", "previous", "timeline", "files"];
    const hashTab = location.hash.replace("#", "") as Tab;
    if (validTabs.includes(hashTab)) {
      dispatch({ type: "SET_TAB", tab: hashTab });
    }
  }, [dispatch]);

  // Derived data: filter → split active/previous
  const filtered = filterSessions(sessions, searchFilter);
  const { active, previous } = splitActivePrevious(filtered, processes);

  // Waiting count for header badge
  const waitingCount = sessions.filter(
    (s) => processes[s.id]?.state === "waiting",
  ).length;

  // Last updated — based on actual fetch timestamp
  const lastUpdated = state.lastFetchedAt
    ? new Date(state.lastFetchedAt).toLocaleTimeString()
    : "-";

  // Current timestamp for Timeline. Date.now() is inherently impure but required
  // for a live timeline — the value refreshes on every poll-triggered re-render.
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();

  // Timeline detail modal (opened from timeline bar clicks)
  const [timelineModal, setTimelineModal] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const handleTimelineDetail = useCallback(
    (id: string, title: string) => setTimelineModal({ id, title }),
    [],
  );

  return (
    <>
      <Header
        initialVersion={INITIAL_VERSION}
        lastUpdated={lastUpdated}
        waitingCount={waitingCount}
      />

      <div className="container">
        {!widgetsCollapsed && <StatsRow active={active} processes={processes} />}
        <TabBar activeCount={active.length} previousCount={previous.length} />
        <SearchBar />

        {/* Active panel */}
        <div
          className={`tab-panel ${currentTab === "active" ? "active" : ""}`}
        >
          {currentView === "tile" ? (
            <SessionGrid sessions={active} processes={processes} isActive />
          ) : (
            <SessionList
              sessions={active}
              processes={processes}
              isActive
              panelId="panel-active"
            />
          )}

          {/* Remote Sessions */}
          {remoteSessions.length > 0 && (
            <div className="remote-sessions-section" style={{ marginTop: "2rem" }}>
              <h3 className="remote-sessions-header">🖥️ Remote Sessions ({remoteSessions.length})</h3>
              {currentView === "tile" ? (
                <SessionGrid sessions={remoteSessions} processes={{}} isActive />
              ) : (
                <SessionList
                  sessions={remoteSessions}
                  processes={{}}
                  isActive
                  panelId="panel-remote"
                />
              )}
            </div>
          )}
        </div>

        {/* Previous panel */}
        <div
          className={`tab-panel ${currentTab === "previous" ? "active" : ""}`}
        >
          {currentView === "tile" ? (
            <SessionGrid sessions={previous} processes={processes} isActive={false} />
          ) : (
            <SessionList
              sessions={previous}
              processes={processes}
              isActive={false}
              panelId="panel-previous"
            />
          )}
        </div>

        {/* Timeline panel */}
        <div
          className={`tab-panel ${currentTab === "timeline" ? "active" : ""}`}
        >
          <Timeline
            sessions={sessions}
            processes={processes}
            now={now}
            onOpenDetail={handleTimelineDetail}
          />
        </div>

        {/* Files panel */}
        <div
          className={`tab-panel ${currentTab === "files" ? "active" : ""}`}
        >
          {currentTab === "files" && <FilesTab />}
        </div>
      </div>

      {/* Timeline detail modal (from clicking a Gantt bar) */}
      {timelineModal && (
        <DetailModal
          sessionId={timelineModal.id}
          title={timelineModal.title}
          processes={processes}
          sessions={sessions}
          onClose={() => setTimelineModal(null)}
        />
      )}

      <Tooltip />
      <ToastContainer />
      <DisconnectOverlay />
      <AutostartPopover />
    </>
  );
}

/** Wrapped with AppProvider so all children can access global state. */
export default function App() {
  return (
    <AppProvider>
      <Dashboard />
    </AppProvider>
  );
}
