/**
 * Component tests — render components with minimal props and assert DOM output.
 */

import { render, screen, fireEvent, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import type { Session, ProcessInfo, ProcessMap } from "../types";
import { AppProvider } from "../state";

// ── Factories ────────────────────────────────────────────────────────────────

function makeSession(overrides: Partial<Session> = {}): Session {
  return {
    id: "test-id",
    cwd: null,
    repository: null,
    branch: null,
    summary: "Test session",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T01:00:00Z",
    created_ago: "1 hour ago",
    time_ago: "1 hour ago",
    turn_count: 5,
    file_count: 3,
    checkpoint_count: 1,
    is_running: false,
    state: null,
    waiting_context: "",
    bg_tasks: 0,
    group: "General",
    recent_activity: null,
    restart_cmd: "copilot",
    mcp_servers: [],
    tool_calls: 10,
    subagent_runs: 2,
    intent: "",
    source: "copilot",
    machine_name: "",
    ...overrides,
  };
}

function makeProcess(overrides: Partial<ProcessInfo> = {}): ProcessInfo {
  return {
    pid: 100,
    parent_pid: 0,
    terminal_pid: 0,
    terminal_name: "",
    cmdline: "",
    yolo: false,
    state: "working",
    waiting_context: "",
    bg_tasks: 0,
    bg_task_list: [],
    mcp_servers: [],
    window_title: "",
    ...overrides,
  };
}

// Stub localStorage
const store: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, val: string) => { store[key] = val; },
  removeItem: (key: string) => { delete store[key]; },
});

// Stub clipboard
vi.stubGlobal("navigator", {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
});
vi.stubGlobal("confirm", vi.fn(() => true));

beforeEach(() => {
  Object.keys(store).forEach((k) => delete store[k]);
});

// Mock fetch globally for components that fetch on mount
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve({ checkpoints: [], refs: [], turns: [], recent_output: [], tool_counts: [], files: [] }),
  });
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function renderWithProvider(ui: React.ReactElement) {
  return render(<AppProvider>{ui}</AppProvider>);
}

// ── SessionCard ──────────────────────────────────────────────────────────────

import SessionCard from "../components/SessionCard";

describe("SessionCard", () => {
  it("renders session summary and timestamp", () => {
    const s = makeSession({ summary: "Fix auth bug", created_ago: "2 hours ago" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText("Fix auth bug")).toBeInTheDocument();
    expect(screen.getByText(/2 hours ago/)).toBeInTheDocument();
  });

  it("shows live-dot when running", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working" });
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(container.querySelector(".live-dot")).not.toBeNull();
  });

  it("shows yolo badge when processInfo has yolo flag", () => {
    const s = makeSession();
    const p = makeProcess({ yolo: true });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/YOLO/)).toBeInTheDocument();
  });

  it("renders (Untitled session) when summary is null", () => {
    const s = makeSession({ summary: null });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText("(Untitled session)")).toBeInTheDocument();
  });

  it("shows turn count badge", () => {
    const s = makeSession({ turn_count: 12 });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/12 turns/)).toBeInTheDocument();
  });

  it("shows checkpoint badge when checkpoint_count > 0", () => {
    const s = makeSession({ checkpoint_count: 3 });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/3 checkpoints/)).toBeInTheDocument();
  });

  it("shows cwd when present", () => {
    const s = makeSession({ cwd: "/home/user/project" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/\/home\/user\/project/)).toBeInTheDocument();
  });

  it("shows branch badge when branch is set", () => {
    const s = makeSession({ branch: "main", repository: "org/repo" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/org\/repo\/main/)).toBeInTheDocument();
  });

  it("copies restart command on copy button click", () => {
    const s = makeSession({ restart_cmd: "copilot resume --session=card-abc" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const copyBtn = screen.getByText("📋 Copy");
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copilot resume --session=card-abc");
  });

  it("copies session ID on ID button click", () => {
    const s = makeSession({ id: "card-sess-id" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const idBtn = screen.getByText("🪪");
    fireEvent.click(idBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("card-sess-id");
  });

  it("toggles star when star button clicked", () => {
    const s = makeSession();
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const starBtn = container.querySelector(".star-btn")!;
    expect(starBtn.textContent).toBe("☆");
    fireEvent.click(starBtn);
    expect(starBtn.textContent).toBe("⭐");
  });
});

// ── SessionTile ──────────────────────────────────────────────────────────────

import SessionTile from "../components/SessionTile";

describe("SessionTile", () => {
  const onOpenDetail = vi.fn();

  beforeEach(() => onOpenDetail.mockClear());

  it("renders session summary", () => {
    const s = makeSession({ summary: "Deploy service" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText("Deploy service")).toBeInTheDocument();
  });

  it("shows live-dot when running", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(container.querySelector(".live-dot")).not.toBeNull();
  });

  it("shows (Untitled session) when summary is null", () => {
    const s = makeSession({ summary: null });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText("(Untitled session)")).toBeInTheDocument();
  });

  it("shows yolo badge when processInfo has yolo flag", () => {
    const s = makeSession();
    const p = makeProcess({ yolo: true });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText("🔥")).toBeInTheDocument();
  });

  it("shows turn count", () => {
    const s = makeSession({ turn_count: 7 });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/7/)).toBeInTheDocument();
  });

  it("shows PID and kill button when running with pid", () => {
    const s = makeSession();
    const p = makeProcess({ pid: 42 });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/PID 42/)).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();
  });

  it("calls onOpenDetail when tile clicked", () => {
    const s = makeSession({ id: "click-id", summary: "Click me" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    fireEvent.click(container.querySelector(".tile-card")!);
    expect(onOpenDetail).toHaveBeenCalledWith("click-id", "Click me");
  });

  it("does not call onOpenDetail for remote session", () => {
    const s = makeSession({ id: "remote-1", machine_name: "remote-host" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    fireEvent.click(container.querySelector(".tile-card")!);
    expect(onOpenDetail).not.toHaveBeenCalled();
  });

  it("copies restart command on copy button click", () => {
    const s = makeSession({ restart_cmd: "copilot resume --session=abc" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const copyBadge = screen.getAllByText("📋")[0];
    fireEvent.click(copyBadge);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copilot resume --session=abc");
  });

  it("copies session ID on ID button click", () => {
    const s = makeSession({ id: "sess-id-copy" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const idBadge = screen.getAllByText("🪪")[0];
    fireEvent.click(idBadge);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("sess-id-copy");
  });

  it("dismisses session on hide badge click", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ success: true, message: "hidden" }),
    });
    const s = makeSession({ id: "dismiss-me" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    fireEvent.click(screen.getByText("🙈"));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith("/api/dismiss/dismiss-me?token=test-token", { method: "POST" });
    });
  });

  it("toggles star when star button clicked", () => {
    const s = makeSession({ id: "star-test" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const starBtn = container.querySelector(".star-btn")!;
    expect(starBtn.textContent).toBe("☆");
    fireEvent.click(starBtn);
    expect(starBtn.textContent).toBe("⭐");
  });

  it("does not show window_title when it matches intent", () => {
    const s = makeSession({ intent: "Fixing auth" });
    const p = makeProcess({ window_title: "🤖 Fixing auth" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(container.querySelector("[data-tip^='Window:']")).toBeNull();
  });
});

// ── SessionList──────────────────────────────────────────────────────────────

import SessionList from "../components/SessionList";

describe("SessionList", () => {
  it("renders empty message for active when no sessions", () => {
    renderWithProvider(
      <SessionList sessions={[]} processes={{}} isActive={true} panelId="active" />,
    );
    // Before first fetch completes, active tab shows loading state
    expect(screen.getByText("Loading sessions…")).toBeInTheDocument();
  });

  it("renders empty message for previous when no sessions", () => {
    renderWithProvider(
      <SessionList sessions={[]} processes={{}} isActive={false} panelId="previous" />,
    );
    expect(screen.getByText("No previous sessions.")).toBeInTheDocument();
  });

  it("renders grouped sessions", () => {
    const sessions = [
      makeSession({ id: "1", summary: "Session one", group: "ProjectA" }),
      makeSession({ id: "2", summary: "Session two", group: "ProjectA" }),
    ];
    renderWithProvider(
      <SessionList sessions={sessions} processes={{}} isActive={true} panelId="active" />,
    );
    expect(screen.getByText("ProjectA")).toBeInTheDocument();
    expect(screen.getByText("Session one")).toBeInTheDocument();
    expect(screen.getByText("Session two")).toBeInTheDocument();
  });

  it("shows group count", () => {
    const sessions = [
      makeSession({ id: "1", group: "MyGroup" }),
      makeSession({ id: "2", group: "MyGroup" }),
      makeSession({ id: "3", group: "MyGroup" }),
    ];
    renderWithProvider(
      <SessionList sessions={sessions} processes={{}} isActive={true} panelId="active" />,
    );
    expect(screen.getByText("(3)")).toBeInTheDocument();
  });
});

// ── StatsRow ─────────────────────────────────────────────────────────────────

import StatsRow from "../components/StatsRow";

describe("StatsRow", () => {
  it("returns null when no active sessions", () => {
    const { container } = render(<StatsRow active={[]} processes={{}} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders running count", () => {
    const active = [makeSession({ id: "a" }), makeSession({ id: "b" })];
    render(<StatsRow active={active} processes={{}} />);
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Running Now")).toBeInTheDocument();
  });

  it("sums turn counts across sessions", () => {
    const active = [
      makeSession({ id: "a", turn_count: 10 }),
      makeSession({ id: "b", turn_count: 20 }),
    ];
    render(<StatsRow active={active} processes={{}} />);
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("sums tool calls across sessions", () => {
    const active = [
      makeSession({ id: "a", tool_calls: 5 }),
      makeSession({ id: "b", tool_calls: 15 }),
    ];
    render(<StatsRow active={active} processes={{}} />);
    expect(screen.getByText("20")).toBeInTheDocument();
  });

  it("sums subagent runs across sessions", () => {
    const active = [
      makeSession({ id: "a", subagent_runs: 3, turn_count: 0, tool_calls: 0 }),
      makeSession({ id: "b", subagent_runs: 7, turn_count: 0, tool_calls: 0 }),
    ];
    render(<StatsRow active={active} processes={{}} />);
    expect(screen.getByText("Sub-agents")).toBeInTheDocument();
    expect(screen.getAllByText("10")).toHaveLength(1);
  });

  it("sums background tasks from processes", () => {
    const active = [makeSession({ id: "a" }), makeSession({ id: "b" })];
    const processes: ProcessMap = {
      a: makeProcess({ bg_tasks: 2 }),
      b: makeProcess({ bg_tasks: 3 }),
    };
    render(<StatsRow active={active} processes={processes} />);
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("Background Tasks")).toBeInTheDocument();
  });
});

// ── TabBar ───────────────────────────────────────────────────────────────────

import TabBar from "../components/TabBar";

describe("TabBar", () => {
  it("renders all four tabs", () => {
    renderWithProvider(<TabBar activeCount={3} previousCount={5} />);
    expect(screen.getByText(/Active/)).toBeInTheDocument();
    expect(screen.getByText(/Previous/)).toBeInTheDocument();
    expect(screen.getByText(/Timeline/)).toBeInTheDocument();
    expect(screen.getByText(/Files/)).toBeInTheDocument();
  });

  it("shows active count badge", () => {
    renderWithProvider(<TabBar activeCount={7} previousCount={0} />);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("shows previous count badge", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={12} />);
    expect(screen.getByText("12")).toBeInTheDocument();
  });

  it("highlights active tab by default", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const activeTab = screen.getByText(/Active/).closest(".tab");
    expect(activeTab?.classList.contains("active")).toBe(true);
  });

  it("renders tile and list view buttons", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    expect(document.querySelector('[data-tip="Tile view"]')).toBeInTheDocument();
    expect(document.querySelector('[data-tip="List view"]')).toBeInTheDocument();
  });

  it("renders notification button", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    expect(screen.getByText(/Notifications/)).toBeInTheDocument();
  });
});

// ── Tooltip ──────────────────────────────────────────────────────────────────

import Tooltip from "../components/Tooltip";

describe("Tooltip", () => {
  it("renders a hidden tooltip element", () => {
    render(<Tooltip />);
    const el = document.getElementById("dash-tooltip");
    expect(el).not.toBeNull();
    expect(el!.style.display).toBe("none");
  });

  it("tooltip element has fixed positioning", () => {
    render(<Tooltip />);
    const el = document.getElementById("dash-tooltip");
    expect(el!.style.position).toBe("fixed");
  });

  it("tooltip element has pointer-events none", () => {
    render(<Tooltip />);
    const el = document.getElementById("dash-tooltip");
    expect(el!.style.pointerEvents).toBe("none");
  });

  it("shows tooltip text on mouseover of data-tip element after delay", async () => {
    vi.useFakeTimers();
    render(
      <div>
        <Tooltip />
        <button data-tip="Hello tooltip">Hover me</button>
      </div>,
    );
    const btn = screen.getByText("Hover me");
    fireEvent.mouseOver(btn, { clientX: 100, clientY: 100 });
    act(() => { vi.advanceTimersByTime(500); });
    const el = document.getElementById("dash-tooltip");
    expect(el!.textContent).toBe("Hello tooltip");
    expect(el!.style.display).toBe("block");
    vi.useRealTimers();
  });

  it("hides tooltip on mouseout", async () => {
    vi.useFakeTimers();
    render(
      <div>
        <Tooltip />
        <button data-tip="Tip text">Hover me</button>
      </div>,
    );
    const btn = screen.getByText("Hover me");
    fireEvent.mouseOver(btn, { clientX: 100, clientY: 100 });
    act(() => { vi.advanceTimersByTime(500); });
    const el = document.getElementById("dash-tooltip");
    expect(el!.style.display).toBe("block");
    fireEvent.mouseOut(btn, { relatedTarget: document.body });
    expect(el!.style.display).toBe("none");
    vi.useRealTimers();
  });

  it("positions tooltip near mouse coordinates", async () => {
    vi.useFakeTimers();
    render(
      <div>
        <Tooltip />
        <button data-tip="Pos test">Hover</button>
      </div>,
    );
    const btn = screen.getByText("Hover");
    fireEvent.mouseOver(btn, { clientX: 50, clientY: 60 });
    act(() => { vi.advanceTimersByTime(500); });
    const el = document.getElementById("dash-tooltip");
    expect(el!.style.left).toBeTruthy();
    expect(el!.style.top).toBeTruthy();
    vi.useRealTimers();
  });

  it("updates position on mousemove when visible", () => {
    vi.useFakeTimers();
    render(
      <div>
        <Tooltip />
        <button data-tip="Move test">Hover</button>
      </div>,
    );
    const btn = screen.getByText("Hover");
    fireEvent.mouseOver(btn, { clientX: 50, clientY: 60 });
    act(() => { vi.advanceTimersByTime(500); });
    const el = document.getElementById("dash-tooltip");
    fireEvent.mouseMove(document, { clientX: 200, clientY: 200 });
    expect(el!.style.left).toBeTruthy();
    vi.useRealTimers();
  });
});

// ── SessionCard (additional coverage) ────────────────────────────────────────

describe("SessionCard — interactions", () => {
  it("shows MCP server badges", () => {
    const s = makeSession({ mcp_servers: ["server-a", "server-b"] });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/server-a/)).toBeInTheDocument();
    expect(screen.getByText(/server-b/)).toBeInTheDocument();
  });

  it("dispatches TOGGLE_STAR on star click", () => {
    const s = makeSession();
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const starBtn = container.querySelector(".star-btn")!;
    fireEvent.click(starBtn);
    expect(starBtn.textContent).toBe("⭐");
  });

  it("copies restart_cmd on copy button click", () => {
    const s = makeSession({ restart_cmd: "copilot resume --id=test" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const copyBtn = screen.getByText("📋 Copy");
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copilot resume --id=test");
  });

  it("copies session id on ID copy button click", () => {
    const s = makeSession({ id: "my-session-id" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const copyBtn = screen.getByText("🪪");
    fireEvent.click(copyBtn);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("my-session-id");
  });

  it("shows focus button when running", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working" });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/Focus/)).toBeInTheDocument();
  });

  it("shows PID and kill button when running with pid", () => {
    const s = makeSession();
    const p = makeProcess({ pid: 999 });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/PID 999/)).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();
  });

  it("shows expanded detail when toggled", async () => {
    const s = makeSession({ id: "expand-test" });
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    const clickArea = container.querySelector("[style*='cursor: pointer']")!;
    fireEvent.click(clickArea);
    await waitFor(() => {
      expect(container.querySelector(".session-card.expanded")).not.toBeNull();
    });
  });

  it("shows recent activity when present", () => {
    const s = makeSession({ recent_activity: "Fixed the login page" });
    renderWithProvider(<SessionCard session={s} processInfo={undefined} />);
    expect(screen.getByText(/Fixed the login page/)).toBeInTheDocument();
  });

  it("shows waiting context when in waiting state", () => {
    const s = makeSession();
    const p = makeProcess({ state: "waiting", waiting_context: "Needs user approval" });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/Needs user approval/)).toBeInTheDocument();
  });

  it("shows state badge when running with known state", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working" });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/Working/)).toBeInTheDocument();
  });

  it("shows bg_tasks badge when background tasks exist", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working", bg_tasks: 3 });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/3 bg tasks/)).toBeInTheDocument();
  });

  it("shows intent as title when running with intent", () => {
    const s = makeSession({ intent: "Refactoring auth module" });
    const p = makeProcess({ state: "working" });
    renderWithProvider(<SessionCard session={s} processInfo={p} />);
    expect(screen.getByText(/Refactoring auth module/)).toBeInTheDocument();
  });

  it("shows waiting live-dot class when state is waiting", () => {
    const s = makeSession();
    const p = makeProcess({ state: "waiting" });
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={p} />);
    const dot = container.querySelector(".live-dot.waiting");
    expect(dot).not.toBeNull();
  });

  it("shows idle live-dot class when state is idle", () => {
    const s = makeSession();
    const p = makeProcess({ state: "idle" });
    const { container } = renderWithProvider(<SessionCard session={s} processInfo={p} />);
    const dot = container.querySelector(".live-dot.idle");
    expect(dot).not.toBeNull();
  });
});

// ── SessionTile (additional coverage) ────────────────────────────────────────

describe("SessionTile — interactions", () => {
  const onOpenDetail = vi.fn();
  beforeEach(() => onOpenDetail.mockClear());

  it("calls onOpenDetail when tile is clicked", () => {
    const s = makeSession({ id: "tile-1", summary: "My session" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    fireEvent.click(container.querySelector(".tile-card")!);
    expect(onOpenDetail).toHaveBeenCalledWith("tile-1", "My session");
  });

  it("dispatches TOGGLE_STAR on star click", () => {
    const s = makeSession({ id: "star-tile" });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const starBtn = container.querySelector(".star-btn")!;
    fireEvent.click(starBtn);
    expect(onOpenDetail).not.toHaveBeenCalled();
    expect(starBtn.textContent).toBe("⭐");
  });

  it("copies restart_cmd on copy badge click", () => {
    const s = makeSession({ restart_cmd: "copilot resume" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const badges = screen.getAllByText("📋");
    fireEvent.click(badges[0]);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("copilot resume");
  });

  it("copies session id on ID badge click", () => {
    const s = makeSession({ id: "tile-copy-id" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    const idBadges = screen.getAllByText("🪪");
    fireEvent.click(idBadges[0]);
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("tile-copy-id");
  });

  it("shows branch badge when branch is set", () => {
    const s = makeSession({ branch: "feature", repository: "acme/app" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/acme\/app\/feature/)).toBeInTheDocument();
  });

  it("shows recent activity when present", () => {
    const s = makeSession({ recent_activity: "Deployed v2" });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText("Deployed v2")).toBeInTheDocument();
  });

  it("shows waiting context when in waiting state", () => {
    const s = makeSession();
    const p = makeProcess({ state: "waiting", waiting_context: "Awaiting review" });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/Awaiting review/)).toBeInTheDocument();
  });

  it("shows checkpoint count when > 0", () => {
    const s = makeSession({ checkpoint_count: 5 });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(container.querySelector(".badge-cp")).not.toBeNull();
    expect(container.querySelector(".badge-cp")!.textContent).toContain("5");
  });

  it("shows MCP server badges", () => {
    const s = makeSession({ mcp_servers: ["mcp-1"] });
    renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/mcp-1/)).toBeInTheDocument();
  });

  it("shows focus badge when running", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working" });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText("👁️")).toBeInTheDocument();
  });

  it("shows bg_tasks badge when background tasks exist", () => {
    const s = makeSession();
    const p = makeProcess({ state: "working", bg_tasks: 2 });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/2 bg/)).toBeInTheDocument();
  });

  it("shows intent as title when running with intent", () => {
    const s = makeSession({ intent: "Building tests" });
    const p = makeProcess({ state: "working" });
    renderWithProvider(
      <SessionTile session={s} processInfo={p} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/Building tests/)).toBeInTheDocument();
  });

  it("passes (Untitled) to onOpenDetail when summary is null", () => {
    const s = makeSession({ id: "no-title", summary: null });
    const { container } = renderWithProvider(
      <SessionTile session={s} processInfo={undefined} onOpenDetail={onOpenDetail} />,
    );
    fireEvent.click(container.querySelector(".tile-card")!);
    expect(onOpenDetail).toHaveBeenCalledWith("no-title", "(Untitled)");
  });
});

// ── TabBar (additional coverage) ─────────────────────────────────────────────

describe("TabBar — interactions", () => {
  it("clicking a tab changes the active tab", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const timelineTab = screen.getByText(/Timeline/).closest(".tab")!;
    fireEvent.click(timelineTab);
    expect(timelineTab.classList.contains("active")).toBe(true);
  });

  it("clicking tile view button activates tile view", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const tileBtn = document.querySelector('[data-tip="Tile view"]') as HTMLElement;
    fireEvent.click(tileBtn);
    expect(tileBtn.classList.contains("active")).toBe(true);
  });

  it("clicking list view button activates list view", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const listBtn = document.querySelector('[data-tip="List view"]') as HTMLElement;
    fireEvent.click(listBtn);
    expect(listBtn.classList.contains("active")).toBe(true);
  });

  it("clicking notification button toggles notification text", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const notifBtn = screen.getByText(/Notifications/);
    // Initial state depends on Notification.permission; just check toggling
    fireEvent.click(notifBtn);
    expect(screen.getByText(/Notifications/)).toBeInTheDocument();
  });

  it("shows popover on mouse enter after delay", () => {
    vi.useFakeTimers();
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const notifBtn = screen.getByText(/Notifications/);
    fireEvent.mouseEnter(notifBtn);
    act(() => { vi.advanceTimersByTime(500); });
    const popover = document.querySelector(".notif-popover");
    expect(popover).not.toBeNull();
    vi.useRealTimers();
  });

  it("hides popover on mouse leave", () => {
    vi.useFakeTimers();
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const notifBtn = screen.getByText(/Notifications/);
    fireEvent.mouseEnter(notifBtn);
    act(() => { vi.advanceTimersByTime(500); });
    fireEvent.mouseLeave(notifBtn);
    const popover = document.querySelector(".notif-popover.visible");
    expect(popover).toBeNull();
    vi.useRealTimers();
  });

  it("all four tab types render with correct data-tab attributes", () => {
    const { container } = renderWithProvider(<TabBar activeCount={1} previousCount={2} />);
    expect(container.querySelector('[data-tab="active"]')).not.toBeNull();
    expect(container.querySelector('[data-tab="previous"]')).not.toBeNull();
    expect(container.querySelector('[data-tab="timeline"]')).not.toBeNull();
    expect(container.querySelector('[data-tab="files"]')).not.toBeNull();
  });

  it("Previous tab becomes active when clicked", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const prevTab = screen.getByText(/Previous/).closest(".tab")!;
    fireEvent.click(prevTab);
    expect(prevTab.classList.contains("active")).toBe(true);
  });

  it("Files tab becomes active when clicked", () => {
    renderWithProvider(<TabBar activeCount={0} previousCount={0} />);
    const filesTab = screen.getByText(/Files/).closest(".tab")!;
    fireEvent.click(filesTab);
    expect(filesTab.classList.contains("active")).toBe(true);
  });
});

// ── Timeline ─────────────────────────────────────────────────────────────────

import Timeline from "../components/Timeline";

describe("Timeline", () => {
  const onOpenDetail = vi.fn();
  const now = new Date("2026-01-03T12:00:00Z").getTime();
  beforeEach(() => onOpenDetail.mockClear());

  it("shows empty message when no sessions", () => {
    render(<Timeline sessions={[]} processes={{}} now={now} onOpenDetail={onOpenDetail} />);
    expect(screen.getByText("No sessions with timestamps.")).toBeInTheDocument();
  });

  it("shows empty message when sessions have no timestamps in range", () => {
    const oldSession = makeSession({
      created_at: "2020-01-01T00:00:00Z",
      updated_at: "2020-01-01T01:00:00Z",
    });
    render(<Timeline sessions={[oldSession]} processes={{}} now={now} onOpenDetail={onOpenDetail} />);
    expect(screen.getByText("No sessions with timestamps.")).toBeInTheDocument();
  });

  it("renders timeline bars for sessions within range", () => {
    const s1 = makeSession({
      id: "t1",
      summary: "Timeline session 1",
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    const s2 = makeSession({
      id: "t2",
      summary: "Timeline session 2",
      created_at: "2026-01-02T14:00:00Z",
      updated_at: "2026-01-02T15:00:00Z",
    });
    render(
      <Timeline sessions={[s1, s2]} processes={{}} now={now} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/Timeline session 1/)).toBeInTheDocument();
    expect(screen.getByText(/Timeline session 2/)).toBeInTheDocument();
  });

  it("clicking a bar calls onOpenDetail", () => {
    const s = makeSession({
      id: "click-bar",
      summary: "Clickable session",
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    const { container } = render(
      <Timeline sessions={[s]} processes={{}} now={now} onOpenDetail={onOpenDetail} />,
    );
    // The clickable area is the bar container div
    const barContainer = container.querySelector('[style*="cursor: pointer"]')!;
    fireEvent.click(barContainer);
    expect(onOpenDetail).toHaveBeenCalledWith("click-bar", "Clickable session");
  });

  it("uses active color for running sessions", () => {
    const s = makeSession({
      id: "running-bar",
      summary: "Running session",
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    const procs: ProcessMap = {
      "running-bar": makeProcess({ state: "working" }),
    };
    render(
      <Timeline sessions={[s]} processes={procs} now={now} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/Running session/)).toBeInTheDocument();
  });

  it("uses waiting color for waiting sessions", () => {
    const s = makeSession({
      id: "waiting-bar",
      summary: "Waiting session",
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    const procs: ProcessMap = {
      "waiting-bar": makeProcess({ state: "waiting" }),
    };
    render(
      <Timeline sessions={[s]} processes={procs} now={now} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/Waiting session/)).toBeInTheDocument();
  });

  it("renders time labels", () => {
    const s = makeSession({
      id: "label-test",
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    const { container } = render(
      <Timeline sessions={[s]} processes={{}} now={now} onOpenDetail={onOpenDetail} />,
    );
    // Should have time label divs
    const labels = container.querySelectorAll('[style*="font-size: 11"]');
    expect(labels.length).toBeGreaterThan(0);
  });

  it("shows (Untitled) for sessions without summary", () => {
    const s = makeSession({
      id: "no-summary",
      summary: null,
      created_at: "2026-01-02T10:00:00Z",
      updated_at: "2026-01-02T11:00:00Z",
    });
    render(
      <Timeline sessions={[s]} processes={{}} now={now} onOpenDetail={onOpenDetail} />,
    );
    expect(screen.getByText(/\(Untitled\)/)).toBeInTheDocument();
  });
});

// ── SessionDetail ────────────────────────────────────────────────────────────

import SessionDetail from "../components/SessionDetail";

describe("SessionDetail", () => {
  it("shows loading state initially", () => {
    mockFetch.mockReturnValue(new Promise(() => {})); // never resolves
    renderWithProvider(<SessionDetail sessionId="loading-test" />);
    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("shows error state when fetch fails", async () => {
    mockFetch.mockRejectedValueOnce(new Error("fail"));
    renderWithProvider(<SessionDetail sessionId="error-test" />);
    await waitFor(() => {
      expect(screen.getByText("Error loading details.")).toBeInTheDocument();
    });
  });

  it("shows empty message when no content", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [],
        turns: [],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="empty-test" />);
    await waitFor(() => {
      expect(screen.getByText("No additional details for this session.")).toBeInTheDocument();
    });
    expect(screen.getByText("📝 Plan")).toBeInTheDocument();
  });

  it("renders checkpoints when present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [{ checkpoint_number: 1, title: "Initial setup", overview: "Set things up", next_steps: "Add tests" }],
        refs: [],
        turns: [],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="cp-test" />);
    await waitFor(() => {
      expect(screen.getByText(/Checkpoints/)).toBeInTheDocument();
      expect(screen.getByText(/Initial setup/)).toBeInTheDocument();
    });
  });

  it("renders refs when present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [{ ref_type: "pr", ref_value: "#42" }],
        turns: [],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="ref-test" />);
    await waitFor(() => {
      expect(screen.getByText(/References/)).toBeInTheDocument();
      expect(screen.getByText(/pr: #42/)).toBeInTheDocument();
    });
  });

  it("renders recent output when present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [],
        turns: [],
        recent_output: ["line1", "line2"],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="output-test" />);
    await waitFor(() => {
      expect(screen.getByText(/Recent Output/)).toBeInTheDocument();
      expect(screen.getByText("line1")).toBeInTheDocument();
      expect(screen.getByText("line2")).toBeInTheDocument();
    });
  });

  it("renders conversation turns when present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [],
        turns: [{ turn_index: 0, user_message: "Hello user", assistant_response: "Hello assistant" }],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="turns-test" />);
    await waitFor(() => {
      expect(screen.getByText(/Conversation/)).toBeInTheDocument();
      expect(screen.getByText(/Hello user/)).toBeInTheDocument();
      expect(screen.getByText(/Hello assistant/)).toBeInTheDocument();
    });
  });

  it("renders tool counts with bars when present", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [],
        turns: [],
        recent_output: [],
        tool_counts: [
          { name: "edit", count: 10 },
          { name: "grep", count: 5 },
        ],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="tools-test" />);
    await waitFor(() => {
      expect(screen.getByText(/Tools used/)).toBeInTheDocument();
      expect(screen.getByText("edit")).toBeInTheDocument();
      expect(screen.getByText("grep")).toBeInTheDocument();
      expect(screen.getByText("10")).toBeInTheDocument();
      expect(screen.getByText("5")).toBeInTheDocument();
    });
  });

  it("expands checkpoint item on click to show overview and next steps", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [{ checkpoint_number: 1, title: "Step one", overview: "Did the first thing", next_steps: "Do the second thing" }],
        refs: [],
        turns: [],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="cp-expand" />);
    await waitFor(() => {
      expect(screen.getByText(/Step one/)).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText(/Step one/).closest(".cp-item")!);
    expect(screen.getByText("Did the first thing")).toBeInTheDocument();
    expect(screen.getByText(/Do the second thing/)).toBeInTheDocument();
  });

  it("truncates long user messages in turns", async () => {
    const longMsg = "x".repeat(300);
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({
        checkpoints: [],
        refs: [],
        turns: [{ turn_index: 0, user_message: longMsg, assistant_response: "ok" }],
        recent_output: [],
        tool_counts: [],
        files: [],
      }),
    });
    renderWithProvider(<SessionDetail sessionId="truncate-test" />);
    await waitFor(() => {
      expect(screen.getByText(/\.\.\./)).toBeInTheDocument();
    });
  });

  it("loads and renders the plan panel on demand", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          checkpoints: [],
          refs: [],
          turns: [],
          recent_output: [],
          tool_counts: [],
          files: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          path: "/repo/PLAN.md",
          content: "# Plan\n\n- [x] done\n- [ ] next",
          mtime: "2026-01-02T00:00:00Z",
          progress: { done: 1, total: 2 },
        }),
      });

    renderWithProvider(<SessionDetail sessionId="plan-test" />);
    fireEvent.click(await screen.findByText("Show"));

    await waitFor(() => {
      expect(screen.getByText("Plan")).toBeInTheDocument();
      expect(screen.getByText("done")).toBeInTheDocument();
      expect(screen.getByText("next")).toBeInTheDocument();
      expect(screen.getByText("/repo/PLAN.md")).toBeInTheDocument();
      expect(screen.getByText(/1\/2 done/)).toBeInTheDocument();
    });
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  });

  it("shows a graceful no-plan state", async () => {
    mockFetch
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          checkpoints: [],
          refs: [],
          turns: [],
          recent_output: [],
          tool_counts: [],
          files: [],
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: () => Promise.resolve({
          path: null,
          content: null,
          mtime: null,
          progress: null,
        }),
      });

    renderWithProvider(<SessionDetail sessionId="plan-empty" />);
    fireEvent.click(await screen.findByText("Show"));

    await waitFor(() => {
      expect(screen.getByText("No plan file.")).toBeInTheDocument();
    });
  });
});

// ── SessionGrid ──────────────────────────────────────────────────────────────

import SessionGrid from "../components/SessionGrid";

describe("SessionGrid", () => {
  it("renders empty message for active when no sessions", () => {
    renderWithProvider(<SessionGrid sessions={[]} processes={{}} isActive={true} />);
    // Before first fetch completes, active tab shows loading state
    expect(screen.getByText("Loading sessions…")).toBeInTheDocument();
  });

  it("renders empty message for previous when no sessions", () => {
    renderWithProvider(<SessionGrid sessions={[]} processes={{}} isActive={false} />);
    expect(screen.getByText("No previous sessions.")).toBeInTheDocument();
  });

  it("renders tiles for sessions", () => {
    const sessions = [
      makeSession({ id: "s1", summary: "First session" }),
      makeSession({ id: "s2", summary: "Second session" }),
    ];
    renderWithProvider(<SessionGrid sessions={sessions} processes={{}} isActive={true} />);
    expect(screen.getByText("First session")).toBeInTheDocument();
    expect(screen.getByText("Second session")).toBeInTheDocument();
  });

  it("shows group headers when groupBy is project", () => {
    store["dash-group-by"] = "project";
    const sessions = [
      makeSession({ id: "s1", summary: "S1", group: "ProjectA" }),
      makeSession({ id: "s2", summary: "S2", group: "ProjectB" }),
    ];
    renderWithProvider(<SessionGrid sessions={sessions} processes={{}} isActive={true} />);
    expect(screen.getByText(/ProjectA/)).toBeInTheDocument();
    expect(screen.getByText(/ProjectB/)).toBeInTheDocument();
    const counts = screen.getAllByText("(1)");
    expect(counts.length).toBe(2);
  });

  it("shows group headers when groupBy is machine", () => {
    store["dash-group-by"] = "machine";
    const sessions = [
      makeSession({ id: "s1", summary: "S1", machine_name: "Desktop" }),
      makeSession({ id: "s2", summary: "S2", machine_name: "Laptop" }),
    ];
    const { container } = renderWithProvider(<SessionGrid sessions={sessions} processes={{}} isActive={true} />);
    const headers = container.querySelectorAll(".group-header");
    expect(headers.length).toBe(2);
    const headerTexts = Array.from(headers).map((h) => h.textContent);
    expect(headerTexts.some((t) => t?.includes("Desktop"))).toBe(true);
    expect(headerTexts.some((t) => t?.includes("Laptop"))).toBe(true);
  });

  it("does not show group headers when groupBy is none", () => {
    const sessions = [
      makeSession({ id: "s1", summary: "S1", group: "SameGroup" }),
      makeSession({ id: "s2", summary: "S2", group: "SameGroup" }),
    ];
    const { container } = renderWithProvider(
      <SessionGrid sessions={sessions} processes={{}} isActive={true} />,
    );
    expect(container.querySelector(".group-header")).toBeNull();
  });

  it("collapses group when header clicked", () => {
    store["dash-group-by"] = "project";
    const sessions = [
      makeSession({ id: "s1", summary: "Visible session", group: "MyGroup" }),
    ];
    const { container } = renderWithProvider(
      <SessionGrid sessions={sessions} processes={{}} isActive={true} />,
    );
    expect(screen.getByText("Visible session")).toBeInTheDocument();
    const header = container.querySelector(".group-header")!;
    fireEvent.click(header);
    expect(screen.queryByText("Visible session")).not.toBeInTheDocument();
  });
});
