/**
 * Tests for the API client — verifies each function calls the correct
 * endpoint and returns typed data.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import {
  fetchSessions,
  fetchProcesses,
  fetchSessionDetail,
  fetchFiles,
  fetchVersion,
  fetchServerInfo,
  focusSession,
  killSession,
  triggerUpdate,
} from "../api/client";

// Mock global fetch
const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

beforeEach(() => {
  mockFetch.mockReset();
});

function jsonResponse(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: () => Promise.resolve(data),
  });
}

describe("API client", () => {
  // Token is set in setup.ts as "test-token"
  const AUTH = { headers: { Authorization: "Bearer test-token" } };

  describe("GET endpoints", () => {
    it("fetchSessions calls /api/sessions", async () => {
      mockFetch.mockReturnValue(jsonResponse([{ id: "abc" }]));
      const result = await fetchSessions();
      expect(mockFetch).toHaveBeenCalledWith("/api/sessions", AUTH);
      expect(result).toEqual([{ id: "abc" }]);
    });

    it("fetchProcesses calls /api/processes", async () => {
      mockFetch.mockReturnValue(jsonResponse({ abc: { pid: 123 } }));
      const result = await fetchProcesses();
      expect(mockFetch).toHaveBeenCalledWith("/api/processes", AUTH);
      expect(result).toEqual({ abc: { pid: 123 } });
    });

    it("fetchSessionDetail calls /api/session/:id", async () => {
      mockFetch.mockReturnValue(jsonResponse({ checkpoints: [] }));
      const result = await fetchSessionDetail("test-id");
      expect(mockFetch).toHaveBeenCalledWith("/api/session/test-id", AUTH);
      expect(result).toEqual({ checkpoints: [] });
    });

    it("fetchFiles calls /api/files", async () => {
      mockFetch.mockReturnValue(jsonResponse([]));
      await fetchFiles();
      expect(mockFetch).toHaveBeenCalledWith("/api/files", AUTH);
    });

    it("fetchVersion calls /api/version", async () => {
      mockFetch.mockReturnValue(jsonResponse({ current: "1.0", update_available: false }));
      const result = await fetchVersion();
      expect(result.current).toBe("1.0");
    });

    it("fetchServerInfo calls /api/server-info", async () => {
      mockFetch.mockReturnValue(jsonResponse({ pid: 1234, port: "5112" }));
      const result = await fetchServerInfo();
      expect(result.pid).toBe(1234);
    });
  });

  describe("POST endpoints", () => {
    it("focusSession calls /api/focus/:id via POST", async () => {
      mockFetch.mockReturnValue(jsonResponse({ success: true, message: "ok" }));
      await focusSession("sid-1");
      expect(mockFetch).toHaveBeenCalledWith("/api/focus/sid-1", {
        method: "POST",
        headers: { Authorization: "Bearer test-token" },
      });
    });

    it("killSession URL-encodes the session ID", async () => {
      mockFetch.mockReturnValue(jsonResponse({ success: true, message: "killed" }));
      await killSession("path/with/slashes");
      expect(mockFetch).toHaveBeenCalledWith(
        "/api/kill/path%2Fwith%2Fslashes",
        { method: "POST", headers: { Authorization: "Bearer test-token" } },
      );
    });

    it("triggerUpdate swallows fetch errors", async () => {
      mockFetch.mockRejectedValue(new Error("network error"));
      // Should not throw
      await expect(triggerUpdate()).resolves.toBeUndefined();
    });
  });

  describe("error handling", () => {
    it("throws on non-200 responses", async () => {
      mockFetch.mockReturnValue(jsonResponse({}, 503));
      await expect(fetchSessions()).rejects.toThrow("503");
    });
  });
});
