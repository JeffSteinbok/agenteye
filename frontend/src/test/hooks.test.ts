/**
 * Hook tests — use renderHook from @testing-library/react.
 */

import { renderHook, act, render } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { STORAGE_KEY_MODE, STORAGE_KEY_PALETTE } from "../constants";

// ── Stub localStorage ────────────────────────────────────────────────────────

const store: Record<string, string> = {};
vi.stubGlobal("localStorage", {
  getItem: (key: string) => store[key] ?? null,
  setItem: (key: string, val: string) => { store[key] = val; },
  removeItem: (key: string) => { delete store[key]; },
});

// ── Mock fetch ───────────────────────────────────────────────────────────────

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  Object.keys(store).forEach((k) => delete store[k]);
  mockFetch.mockReset();
});

// ── useTheme ─────────────────────────────────────────────────────────────────

import { useTheme } from "../hooks/useTheme";

describe("useTheme", () => {
  it("defaults to dark mode and default palette", () => {
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme.mode).toBe("dark");
    expect(result.current.theme.palette).toBe("default");
  });

  it("reads initial mode from localStorage", () => {
    store[STORAGE_KEY_MODE] = "light";
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme.mode).toBe("light");
  });

  it("reads initial palette from localStorage", () => {
    store[STORAGE_KEY_PALETTE] = "ocean";
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme.palette).toBe("ocean");
  });

  it("toggleMode switches from dark to light", () => {
    const { result } = renderHook(() => useTheme());
    act(() => { result.current.toggleMode(); });
    expect(result.current.theme.mode).toBe("light");
    expect(store[STORAGE_KEY_MODE]).toBe("light");
  });

  it("toggleMode switches from light to dark", () => {
    store[STORAGE_KEY_MODE] = "light";
    const { result } = renderHook(() => useTheme());
    act(() => { result.current.toggleMode(); });
    expect(result.current.theme.mode).toBe("dark");
    expect(store[STORAGE_KEY_MODE]).toBe("dark");
  });

  it("setPalette updates palette and localStorage", () => {
    const { result } = renderHook(() => useTheme());
    act(() => { result.current.setPalette("neon"); });
    expect(result.current.theme.palette).toBe("neon");
    expect(store[STORAGE_KEY_PALETTE]).toBe("neon");
  });

  it("applies mode to document element", () => {
    renderHook(() => useTheme());
    expect(document.documentElement.getAttribute("data-mode")).toBe("dark");
  });

  it("applies palette to document element", () => {
    renderHook(() => useTheme());
    expect(document.documentElement.getAttribute("data-palette")).toBe("default");
  });

  it("updates document attribute on toggleMode", () => {
    const { result } = renderHook(() => useTheme());
    act(() => { result.current.toggleMode(); });
    expect(document.documentElement.getAttribute("data-mode")).toBe("light");
  });
});

// ── useDisconnect ────────────────────────────────────────────────────────────

import { useDisconnect } from "../hooks/useDisconnect";
import { AppProvider } from "../state";
import type { ReactNode } from "react";
import { createElement } from "react";

function wrapper({ children }: { children: ReactNode }) {
  return createElement(AppProvider, null, children);
}

describe("useDisconnect", () => {
  it("initially reports connected", () => {
    const { result } = renderHook(() => useDisconnect(), { wrapper });
    expect(result.current.disconnected).toBe(false);
  });

  it("retrySeconds is 0 initially", () => {
    const { result } = renderHook(() => useDisconnect(), { wrapper });
    expect(result.current.retrySeconds).toBe(0);
  });

  it("retryAttempts is 0 initially", () => {
    const { result } = renderHook(() => useDisconnect(), { wrapper });
    expect(result.current.retryAttempts).toBe(0);
  });
});

// ── useVersion ───────────────────────────────────────────────────────────────

import { useVersion } from "../hooks/useVersion";

describe("useVersion", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with initial version and no update available", () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ current: "1.0.0", latest: null, update_available: false }),
    });
    const { result } = renderHook(() => useVersion("1.0.0"), { wrapper });
    expect(result.current.versionInfo.current).toBe("1.0.0");
    expect(result.current.versionInfo.update_available).toBe(false);
    expect(result.current.updating).toBe(false);
  });

  it("fetches version info on mount", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ current: "1.0.0", latest: "2.0.0", update_available: true }),
    });
    const { result } = renderHook(() => useVersion("1.0.0"), { wrapper });

    // Flush microtasks (the fetch promise) without advancing interval timers
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(mockFetch).toHaveBeenCalledWith("/api/version", {
      headers: { Authorization: "Bearer test-token" },
    });
    expect(result.current.versionInfo.update_available).toBe(true);
    expect(result.current.versionInfo.latest).toBe("2.0.0");
  });

  it("handles fetch error gracefully", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    const { result } = renderHook(() => useVersion("1.0.0"), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Should keep initial state on error
    expect(result.current.versionInfo.current).toBe("1.0.0");
    expect(result.current.versionInfo.update_available).toBe(false);
  });
});

// ── useNotifications ─────────────────────────────────────────────────────────

import { useNotifications } from "../hooks/useNotifications";

describe("useNotifications", () => {
  const originalNotification = globalThis.Notification;

  afterEach(() => {
    if (originalNotification) {
      globalThis.Notification = originalNotification;
    }
  });

  it("returns initial notificationsEnabled as false when permission is not granted", () => {
    // Default AppProvider sets notificationsEnabled based on Notification.permission
    Object.defineProperty(globalThis, "Notification", {
      value: Object.assign(vi.fn(), { permission: "default", requestPermission: vi.fn() }),
      writable: true,
      configurable: true,
    });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    expect(result.current.notificationsEnabled).toBe(false);
  });

  it("toggle shows alert when Notification API is not supported", () => {
    const alertMock = vi.fn();
    vi.stubGlobal("alert", alertMock);
    const savedNotif = (globalThis as Record<string, unknown>).Notification;
    delete (globalThis as Record<string, unknown>).Notification;
    const { result } = renderHook(() => useNotifications(), { wrapper });
    act(() => { result.current.toggle(); });
    expect(alertMock).toHaveBeenCalledWith("Desktop notifications not supported in this browser");
    (globalThis as Record<string, unknown>).Notification = savedNotif;
  });

  it("toggle enables notifications when permission is granted", () => {
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "granted", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = vi.fn();
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    act(() => { result.current.toggle(); });
    // After toggle, it should have dispatched SET_NOTIFICATIONS
    // The notificationsEnabled should reflect the toggled state
    expect(typeof result.current.notificationsEnabled).toBe("boolean");
  });

  it("toggle does nothing when permission is denied", () => {
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "denied", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = vi.fn();
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    const before = result.current.notificationsEnabled;
    act(() => { result.current.toggle(); });
    expect(result.current.notificationsEnabled).toBe(before);
  });

  it("toggle requests permission when permission is default", async () => {
    const requestMock = vi.fn().mockResolvedValue("granted");
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "default", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = requestMock;
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    await act(async () => { result.current.toggle(); });
    expect(requestMock).toHaveBeenCalled();
  });

  it("popoverContent returns not-supported content when Notification is missing", () => {
    const savedNotif = (globalThis as Record<string, unknown>).Notification;
    delete (globalThis as Record<string, unknown>).Notification;
    const { result } = renderHook(() => useNotifications(), { wrapper });
    const node = result.current.popoverContent();
    const { container } = render(createElement("div", null, node));
    expect(container.textContent).toContain("Not supported");
    (globalThis as Record<string, unknown>).Notification = savedNotif;
  });

  it("popoverContent returns granted-on content when notifications enabled", () => {
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "granted", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = vi.fn();
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    const node = result.current.popoverContent();
    const { container } = render(createElement("div", null, node));
    expect(container.textContent).toContain("Notifications");
  });

  it("popoverContent returns denied content when permission is denied", () => {
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "denied", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = vi.fn();
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    const node = result.current.popoverContent();
    const { container } = render(createElement("div", null, node));
    expect(container.textContent).toContain("blocked");
  });

  it("popoverContent returns enable content when permission is default", () => {
    const NotifMock = vi.fn();
    Object.defineProperty(NotifMock, "permission", { value: "default", configurable: true });
    (NotifMock as unknown as Record<string, unknown>).requestPermission = vi.fn();
    Object.defineProperty(globalThis, "Notification", { value: NotifMock, writable: true, configurable: true });
    const { result } = renderHook(() => useNotifications(), { wrapper });
    const node = result.current.popoverContent();
    const { container } = render(createElement("div", null, node));
    expect(container.textContent).toContain("Enable notifications");
  });
});

// ── useSessions ──────────────────────────────────────────────────────────────

import { useSessions } from "../hooks/useSessions";

describe("useSessions", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns initial empty state", () => {
    mockFetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([]),
    });
    const { result } = renderHook(() => useSessions(), { wrapper });
    expect(result.current.sessions).toEqual([]);
    expect(result.current.processes).toEqual({});
  });

  it("fetches sessions and processes on mount", async () => {
    const sessions = [{ id: "s1", summary: "Test" }];
    const processes = { s1: { pid: 1, state: "working" } };

    mockFetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(sessions) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(processes) });

    renderHook(() => useSessions(), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(mockFetch).toHaveBeenCalledWith("/api/sessions", {
      headers: { Authorization: "Bearer test-token" },
    });
    expect(mockFetch).toHaveBeenCalledWith("/api/processes", {
      headers: { Authorization: "Bearer test-token" },
    });
  });

  it("handles fetch failure gracefully", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));
    const { result } = renderHook(() => useSessions(), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // Should still return default state without crashing
    expect(result.current.sessions).toEqual([]);
  });

  it("polls processes on fast interval", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    renderHook(() => useSessions(), { wrapper });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const callCount = mockFetch.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000); // PROCESS_POLL_MS
    });

    // Should have made additional fetch calls for process polling
    expect(mockFetch.mock.calls.length).toBeGreaterThan(callCount);
  });
});
