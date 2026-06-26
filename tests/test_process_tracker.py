"""Tests for process_tracker.py — event parsing and session state detection."""

import json
import os
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.models import ProcessInfo, SessionState
from src.process_tracker import (
    _event_data_cache,
    _get_live_branch,
    _get_running_sessions_unix,
    _get_running_sessions_windows,
    _get_session_state,
    _match_process_to_session,
    _parse_iso_timestamp,
    _parse_mcp_servers,
    _read_event_data,
    _read_recent_events,
    _running_cache,
    build_unix_process_map,
    find_terminal_via_map,
    get_recent_output,
    get_running_sessions,
    get_session_event_data,
)

EVENTS_DIR = os.path.join(os.path.expanduser("~"), ".copilot", "session-state")


# ---------------------------------------------------------------------------
# _parse_iso_timestamp
# ---------------------------------------------------------------------------


class TestParseIsoTimestamp:
    def test_valid_iso_string(self):
        ts = "2026-01-15T10:30:00+00:00"
        result = _parse_iso_timestamp(ts)
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 15

    def test_z_suffix(self):
        ts = "2026-01-15T10:30:00Z"
        result = _parse_iso_timestamp(ts)
        assert result.year == 2026

    def test_invalid_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            _parse_iso_timestamp("not-a-timestamp")


# ---------------------------------------------------------------------------
# _parse_mcp_servers
# ---------------------------------------------------------------------------


class TestParseMcpServers:
    def test_no_flag_returns_empty(self):
        assert _parse_mcp_servers("copilot --resume abc-123") == []

    def test_missing_file_returns_empty(self, tmp_path):
        config_path = str(tmp_path / "nonexistent.json")
        cmdline = f"copilot --additional-mcp-config {config_path}"
        assert _parse_mcp_servers(cmdline) == []

    def test_valid_config_returns_server_names(self, tmp_path):
        config = {"mcpServers": {"github": {}, "slack": {}}}
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))
        cmdline = f"copilot --additional-mcp-config {config_file}"
        result = _parse_mcp_servers(cmdline)
        assert set(result) == {"github", "slack"}

    def test_empty_mcp_servers_returns_empty(self, tmp_path):
        config = {"mcpServers": {}}
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))
        cmdline = f"copilot --additional-mcp-config {config_file}"
        assert _parse_mcp_servers(cmdline) == []

    def test_malformed_json_returns_empty(self, tmp_path):
        config_file = tmp_path / "mcp.json"
        config_file.write_text("not valid json")
        cmdline = f"copilot --additional-mcp-config {config_file}"
        assert _parse_mcp_servers(cmdline) == []


# ---------------------------------------------------------------------------
# _read_recent_events
# ---------------------------------------------------------------------------


class TestReadRecentEvents:
    def test_missing_file_returns_empty(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _read_recent_events("nonexistent-session")
        assert result == []

    def test_reads_last_n_events(self, tmp_path, make_events):
        events = [{"type": f"event.{i}", "data": {}} for i in range(20)]
        make_events("sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _read_recent_events("sess-1", count=5)
        assert len(result) == 5
        assert result[-1]["type"] == "event.19"

    def test_skips_malformed_lines(self, tmp_path):
        session_dir = tmp_path / "sess-bad"
        session_dir.mkdir()
        events_file = session_dir / "events.jsonl"
        events_file.write_text('{"type": "good"}\nnot json\n{"type": "also good"}\n')
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _read_recent_events("sess-bad", count=10)
        assert len(result) == 2
        assert all("type" in e for e in result)

    def test_empty_file_returns_empty(self, tmp_path):
        session_dir = tmp_path / "sess-empty"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("")
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _read_recent_events("sess-empty")
        assert result == []


# ---------------------------------------------------------------------------
# _get_session_state
# ---------------------------------------------------------------------------


class TestGetSessionState:
    def _write_events(self, tmp_path, session_id, events):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        events_file = session_dir / "events.jsonl"
        with open(events_file, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_no_events_returns_unknown(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("nonexistent")
        assert result["state"] == "unknown"

    def test_ask_user_tool_returns_waiting(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {
                    "toolCallId": "tc1",
                    "toolName": "ask_user",
                    "arguments": {"question": "What should I do?", "choices": ["A", "B"]},
                },
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "waiting"
        assert "What should I do?" in result["waiting_context"]
        assert "A" in result["waiting_context"]

    def test_pending_tool_returns_working(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {"toolCallId": "tc1", "toolName": "view", "arguments": {}},
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "working"

    def test_completed_tool_returns_idle(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {"toolCallId": "tc1", "toolName": "view", "arguments": {}},
            },
            {
                "type": "tool.execution_complete",
                "data": {"toolCallId": "tc1"},
            },
            {"type": "assistant.turn_end", "data": {}},
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "idle"

    def test_user_message_returns_thinking(self, tmp_path):
        events = [{"type": "user.message", "data": {"message": "do something"}}]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "thinking"

    def test_subagent_started_returns_working(self, tmp_path):
        events = [{"type": "subagent.started", "data": {}}]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "working"

    def test_stale_pending_tool_returns_waiting(self, tmp_path):
        old_time = (datetime.now(UTC) - timedelta(seconds=120)).isoformat()
        events = [
            {
                "type": "tool.execution_start",
                "timestamp": old_time,
                "data": {"toolCallId": "tc1", "toolName": "view", "arguments": {}},
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-1")
        assert result["state"] == "waiting"


# ---------------------------------------------------------------------------
# _match_process_to_session
# ---------------------------------------------------------------------------


class TestMatchProcessToSession:
    def _write_session_start(self, tmp_path, session_id, timestamp):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        event = {"type": "session.start", "timestamp": timestamp, "data": {}}
        (session_dir / "events.jsonl").write_text(json.dumps(event) + "\n")

    def _write_lifecycle_events(self, tmp_path, session_id, events):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "events.jsonl", "w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")

    def test_matches_within_tolerance(self, tmp_path):
        ts = datetime.now(UTC)
        self._write_session_start(tmp_path, "sess-match", ts.isoformat())
        # Process created 3 seconds before the session.start event
        proc_ts = (ts - timedelta(seconds=3)).isoformat()
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _match_process_to_session(proc_ts)
        assert result == "sess-match"

    def test_no_match_beyond_tolerance(self, tmp_path):
        ts = datetime.now(UTC)
        self._write_session_start(tmp_path, "sess-far", ts.isoformat())
        # Process created 31 seconds away — beyond the tolerance window
        proc_ts = (ts - timedelta(seconds=31)).isoformat()
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _match_process_to_session(proc_ts)
        assert result is None

    def test_matches_resume_event_not_just_first_line(self, tmp_path):
        start_ts = datetime.now(UTC)
        resume_ts = start_ts + timedelta(hours=1)
        self._write_lifecycle_events(
            tmp_path,
            "sess-resume",
            [
                {"type": "session.start", "timestamp": start_ts.isoformat(), "data": {}},
                {"type": "session.resume", "timestamp": resume_ts.isoformat(), "data": {}},
            ],
        )
        proc_ts = (resume_ts - timedelta(seconds=12)).isoformat()
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _match_process_to_session(proc_ts)
        assert result == "sess-resume"

    def test_invalid_creation_date_returns_none(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _match_process_to_session("not-a-date")
        assert result is None


# ---------------------------------------------------------------------------
# _read_event_data
# ---------------------------------------------------------------------------


class TestReadEventData:
    def _write_events(self, tmp_path, session_id, events):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_missing_file_returns_defaults(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("nonexistent")
        assert data.tool_calls == 0
        assert data.mcp_servers == []
        assert data.intent == ""

    def test_reads_session_context(self, tmp_path):
        events = [
            {
                "type": "session.start",
                "data": {
                    "context": {
                        "cwd": "/project",
                        "branch": "main",
                        "repository": "owner/repo",
                    }
                },
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-1")
        assert data.cwd == "/project"
        assert data.branch == "main"
        assert data.repository == "owner/repo"

    def test_counts_tool_calls(self, tmp_path):
        events = [
            {"type": "tool.execution_complete", "data": {}},
            {"type": "tool.execution_complete", "data": {}},
            {"type": "tool.execution_complete", "data": {}},
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-1")
        assert data.tool_calls == 3

    def test_reads_intent(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "report_intent",
                    "arguments": {"intent": "Fixing the bug"},
                },
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-1")
        assert data.intent == "Fixing the bug"

    def test_reads_mcp_servers_from_info_event(self, tmp_path):
        events = [
            {
                "type": "info",
                "data": {
                    "infoType": "mcp",
                    "message": "Configured MCP servers: github, slack",
                },
            }
        ]
        self._write_events(tmp_path, "sess-1", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-1")
        assert "github" in data.mcp_servers
        assert "slack" in data.mcp_servers


# ---------------------------------------------------------------------------
# get_session_event_data (caching)
# ---------------------------------------------------------------------------


class TestGetSessionEventData:
    def test_inactive_session_is_cached(self, tmp_path):
        _event_data_cache.clear()
        session_dir = tmp_path / "sess-cache"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("")

        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result1 = get_session_event_data("sess-cache", is_running=False)
            result2 = get_session_event_data("sess-cache", is_running=False)

        assert result1 is result2  # same object from cache

    def test_active_session_not_cached(self, tmp_path):
        _event_data_cache.clear()
        session_dir = tmp_path / "sess-active"
        session_dir.mkdir()
        (session_dir / "events.jsonl").write_text("")

        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result1 = get_session_event_data("sess-active", is_running=True)
            result2 = get_session_event_data("sess-active", is_running=True)

        # Active sessions are re-read each time, not the same cached object
        assert "sess-active" not in _event_data_cache


# ---------------------------------------------------------------------------
# get_recent_output
# ---------------------------------------------------------------------------


class TestGetRecentOutput:
    def test_missing_file_returns_empty(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = get_recent_output("nonexistent")
        assert result == []

    def test_returns_last_tool_output(self, tmp_path):
        session_dir = tmp_path / "sess-1"
        session_dir.mkdir()
        events = [
            {
                "type": "tool.execution_complete",
                "data": {"result": {"content": "line1\nline2\nline3"}},
            }
        ]
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = get_recent_output("sess-1", max_lines=10)
        assert "line1" in result

    def test_skips_intent_logged_content(self, tmp_path):
        session_dir = tmp_path / "sess-1"
        session_dir.mkdir()
        events = [
            {
                "type": "tool.execution_complete",
                "data": {"result": {"content": "Intent logged"}},
            }
        ]
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = get_recent_output("sess-1")
        assert result == []


# ---------------------------------------------------------------------------
# _get_live_branch (lines 517-537)
# ---------------------------------------------------------------------------


class TestGetLiveBranch:
    def test_reads_branch_from_git_head(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        result = _get_live_branch(str(tmp_path))
        assert result == "main"

    def test_reads_feature_branch(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/feature/my-feature\n")
        result = _get_live_branch(str(tmp_path))
        assert result == "feature/my-feature"

    def test_detached_head_returns_empty(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("abc123def456789\n")
        result = _get_live_branch(str(tmp_path))
        assert result == ""

    def test_missing_git_directory_returns_empty(self, tmp_path):
        result = _get_live_branch(str(tmp_path / "no-such-dir"))
        assert result == ""

    def test_empty_cwd_returns_empty(self):
        assert _get_live_branch("") == ""

    def test_walks_up_to_find_git_root(self, tmp_path):
        # Simulate a subdirectory without its own .git
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/develop\n")
        sub = tmp_path / "src" / "deep"
        sub.mkdir(parents=True)
        result = _get_live_branch(str(sub))
        assert result == "develop"


# ---------------------------------------------------------------------------
# _read_event_data — additional event data extraction tests
# ---------------------------------------------------------------------------


class TestReadEventDataExtraction:
    def _write_events(self, tmp_path, session_id, events):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_extracts_intent_from_report_intent(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "report_intent",
                    "arguments": {"intent": "Exploring codebase"},
                },
            },
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "report_intent",
                    "arguments": {"intent": "Fixing CSS bug"},
                },
            },
        ]
        self._write_events(tmp_path, "sess-intent", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-intent")
        # Should capture the last intent
        assert data.intent == "Fixing CSS bug"

    def test_extracts_mcp_from_github_mcp_server(self, tmp_path):
        events = [
            {
                "type": "info",
                "data": {
                    "infoType": "mcp",
                    "message": "GitHub MCP Server connected",
                },
            }
        ]
        self._write_events(tmp_path, "sess-mcp", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-mcp")
        assert data.mcp_servers == ["github"]

    def test_counts_tool_calls_and_subagents(self, tmp_path):
        events = [
            {"type": "tool.execution_complete", "data": {}},
            {"type": "tool.execution_complete", "data": {}},
            {"type": "subagent.completed", "data": {}},
            {"type": "tool.execution_complete", "data": {}},
            {"type": "subagent.completed", "data": {}},
        ]
        self._write_events(tmp_path, "sess-counts", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-counts")
        assert data.tool_calls == 3
        assert data.subagent_runs == 2

    def test_extracts_mcp_servers_list(self, tmp_path):
        events = [
            {
                "type": "info",
                "data": {
                    "infoType": "mcp",
                    "message": "Configured MCP servers: github, slack, jira",
                },
            }
        ]
        self._write_events(tmp_path, "sess-mcp-list", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-mcp-list")
        assert set(data.mcp_servers) == {"github", "slack", "jira"}

    def test_intent_from_string_arguments(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {
                    "toolName": "report_intent",
                    "arguments": json.dumps({"intent": "Creating tests"}),
                },
            }
        ]
        self._write_events(tmp_path, "sess-str-args", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            data = _read_event_data("sess-str-args")
        assert data.intent == "Creating tests"


# ---------------------------------------------------------------------------
# _get_session_state — additional tests (lines 440-458)
# ---------------------------------------------------------------------------


class TestGetSessionStateAdditional:
    def _write_events(self, tmp_path, session_id, events):
        session_dir = tmp_path / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        with open(session_dir / "events.jsonl", "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_returns_default_state_when_no_events(self, tmp_path):
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("no-such-session")
        assert result["state"] == "unknown"
        assert result["waiting_context"] == ""
        assert result["bg_tasks"] == 0

    def test_ask_permission_returns_waiting(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {
                    "toolCallId": "tc1",
                    "toolName": "ask_permission",
                    "arguments": {"question": "Allow file edit?", "choices": ["Yes", "No"]},
                },
            }
        ]
        self._write_events(tmp_path, "sess-perm", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-perm")
        assert result["state"] == "waiting"
        assert "Allow file edit?" in result["waiting_context"]

    def test_counts_subagent_bg_tasks(self, tmp_path):
        events = [
            {"type": "subagent.started", "data": {"toolCallId": "sa1", "agentName": "explore"}},
            {"type": "subagent.started", "data": {"toolCallId": "sa2", "agentName": "task"}},
            {"type": "subagent.completed", "data": {"toolCallId": "sa1"}},
            {"type": "user.message", "data": {"message": "next"}},
        ]
        self._write_events(tmp_path, "sess-bg", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-bg")
        assert result["bg_tasks"] == 1  # 2 started - 1 completed
        assert result["state"] == "thinking"

    def test_tool_complete_then_thinking(self, tmp_path):
        events = [
            {
                "type": "tool.execution_start",
                "data": {"toolCallId": "tc1", "toolName": "grep", "arguments": {}},
            },
            {"type": "tool.execution_complete", "data": {"toolCallId": "tc1"}},
            {"type": "assistant.message", "data": {}},
        ]
        self._write_events(tmp_path, "sess-think", events)
        with patch("src.process_tracker.EVENTS_DIR", str(tmp_path)):
            result = _get_session_state("sess-think")
        assert result["state"] == "thinking"


# ---------------------------------------------------------------------------
# build_unix_process_map / find_terminal_via_map
# ---------------------------------------------------------------------------


class TestUnixProcessMap:
    """Tests for the in-memory process-tree helpers."""

    def test_build_map_parses_pid_ppid_comm(self):
        out = "9643 4510 copilot\n4510 1000 bash\n1000 1 /Applications/iTerm.app/Contents/MacOS/iTerm2\n"
        mock = MagicMock(returncode=0, stdout=out)
        with patch("src.process_tracker.subprocess.run", return_value=mock):
            proc_map = build_unix_process_map()
        assert proc_map[9643] == (4510, "copilot")
        assert proc_map[4510] == (1000, "bash")
        # comm with spaces (full path) is preserved as the remainder
        assert proc_map[1000][0] == 1
        assert proc_map[1000][1].endswith("iTerm2")

    def test_build_map_skips_malformed_and_header_lines(self):
        out = "PID PPID COMM\n9643 4510 copilot\njunk\n123\n"
        mock = MagicMock(returncode=0, stdout=out)
        with patch("src.process_tracker.subprocess.run", return_value=mock):
            proc_map = build_unix_process_map()
        assert proc_map == {9643: (4510, "copilot")}

    def test_build_map_returns_empty_on_failure(self):
        mock = MagicMock(returncode=1, stdout="")
        with patch("src.process_tracker.subprocess.run", return_value=mock):
            assert build_unix_process_map() == {}

    def test_build_map_returns_empty_on_exception(self):
        with patch(
            "src.process_tracker.subprocess.run", side_effect=OSError("boom")
        ):
            assert build_unix_process_map() == {}

    def test_find_terminal_walks_up_to_terminal(self):
        proc_map = {9643: (4510, "copilot"), 4510: (1000, "bash"), 1000: (1, "iTerm2")}
        pid, name = find_terminal_via_map(4510, proc_map, 5)
        assert pid == 1000
        assert name == "iTerm2"

    def test_find_terminal_returns_zero_when_none_found(self):
        proc_map = {4510: (1000, "bash"), 1000: (1, "launchd")}
        assert find_terminal_via_map(4510, proc_map, 5) == (0, "")

    def test_find_terminal_respects_max_depth(self):
        # Terminal is 3 hops up but max_depth is 2 — should not be found
        proc_map = {10: (20, "a"), 20: (30, "b"), 30: (1, "warp")}
        assert find_terminal_via_map(10, proc_map, 2) == (0, "")

    def test_find_terminal_handles_missing_pid(self):
        assert find_terminal_via_map(999, {}, 5) == (0, "")


# ---------------------------------------------------------------------------
# _get_running_sessions_unix (lines 323-406)
# ---------------------------------------------------------------------------


class TestGetRunningSessionsUnix:
    """Tests for _get_running_sessions_unix()."""

    def _make_ps_output(self, lines):
        header = "  PID  PPID                          STARTED COMMAND"
        return header + "\n" + "\n".join(lines) + "\n"

    def test_resume_flag_extracts_session_id(self):
        ps_out = self._make_ps_output([
            " 9643  4510 Wed Feb 25 21:15:57 2026 /opt/homebrew/lib/node_modules/@github/copilot/copilot --resume abc-123-def",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)
        mock_parent = MagicMock(returncode=1, stdout="")

        def run_side_effect(args, **kw):
            if "axo" in args:
                return mock_ps
            return mock_parent

        with patch("src.process_tracker.subprocess.run", side_effect=run_side_effect):
            sessions = _get_running_sessions_unix()

        assert "abc-123-def" in sessions
        assert sessions["abc-123-def"].pid == 9643
        assert sessions["abc-123-def"].parent_pid == 4510

    def test_no_resume_falls_back_to_timestamp(self):
        ps_out = self._make_ps_output([
            " 8560  8559 Wed Feb 25 21:14:56 2026 /opt/homebrew/lib/node_modules/@github/copilot/copilot --yolo",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)
        mock_parent = MagicMock(returncode=1, stdout="")

        def run_side_effect(args, **kw):
            if "axo" in args:
                return mock_ps
            return mock_parent

        with (
            patch("src.process_tracker.subprocess.run", side_effect=run_side_effect),
            patch(
                "src.process_tracker._match_process_to_session",
                return_value="ts-matched",
            ),
        ):
            sessions = _get_running_sessions_unix()

        assert "ts-matched" in sessions
        assert sessions["ts-matched"].yolo is True

    def test_skips_non_copilot_lines(self):
        ps_out = self._make_ps_output([
            " 1234  1000 Wed Feb 25 21:14:56 2026 /usr/bin/python3 script.py",
            " 5678  1000 Wed Feb 25 21:14:56 2026 /usr/bin/bash",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)

        with patch("src.process_tracker.subprocess.run", return_value=mock_ps):
            sessions = _get_running_sessions_unix()

        assert sessions == {}

    def test_subprocess_failure_returns_empty(self):
        mock_result = MagicMock(returncode=1, stdout="error output")

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_unix()

        assert sessions == {}

    def test_empty_ps_output_returns_empty(self):
        mock_result = MagicMock(returncode=0, stdout="")

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_unix()

        assert sessions == {}

    def test_parent_walking_finds_terminal(self):
        ps_out = self._make_ps_output([
            " 9643  4510 Wed Feb 25 21:15:57 2026 /opt/homebrew/lib/node_modules/@github/copilot/copilot --resume sess-term",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)
        # Process map (pid ppid comm) walked in memory: 4510 bash -> 1000 iTerm2
        proc_map_out = "9643 4510 copilot\n4510 1000 bash\n1000 1 iTerm2\n"
        mock_map = MagicMock(returncode=0, stdout=proc_map_out)

        def run_side_effect(args, **kw):
            if "pid=,ppid=,comm=" in args:
                return mock_map
            if "axo" in args:
                return mock_ps
            return MagicMock(returncode=1, stdout="")

        with patch("src.process_tracker.subprocess.run", side_effect=run_side_effect):
            sessions = _get_running_sessions_unix()

        assert sessions["sess-term"].terminal_pid == 1000
        assert sessions["sess-term"].terminal_name == "iTerm2"

    def test_yolo_flag_detected(self):
        ps_out = self._make_ps_output([
            " 8560  8559 Wed Feb 25 21:14:56 2026 /opt/homebrew/lib/node_modules/@github/copilot/copilot --yolo --resume yolo-sess",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)
        mock_parent = MagicMock(returncode=1, stdout="")

        def run_side_effect(args, **kw):
            if "axo" in args:
                return mock_ps
            return mock_parent

        with patch("src.process_tracker.subprocess.run", side_effect=run_side_effect):
            sessions = _get_running_sessions_unix()

        assert sessions["yolo-sess"].yolo is True

    def test_mcp_server_parsed_from_cmdline(self, tmp_path):
        config = {"mcpServers": {"github": {}, "slack": {}}}
        config_file = tmp_path / "mcp.json"
        config_file.write_text(json.dumps(config))

        ps_out = self._make_ps_output([
            f" 9643  4510 Wed Feb 25 21:15:57 2026 /opt/homebrew/lib/node_modules/@github/copilot/copilot --resume mcp-sess --additional-mcp-config {config_file}",
        ])
        mock_ps = MagicMock(returncode=0, stdout=ps_out)
        mock_parent = MagicMock(returncode=1, stdout="")

        def run_side_effect(args, **kw):
            if "axo" in args:
                return mock_ps
            return mock_parent

        with patch("src.process_tracker.subprocess.run", side_effect=run_side_effect):
            sessions = _get_running_sessions_unix()

        assert set(sessions["mcp-sess"].mcp_servers) == {"github", "slack"}


# ---------------------------------------------------------------------------
# _get_running_sessions_windows (lines 240-320)
# ---------------------------------------------------------------------------


class TestGetRunningSessionsWindows:
    """Tests for _get_running_sessions_windows()."""

    def test_resume_flag_extracts_session_id(self):
        procs = [
            {
                "ProcessId": 1234,
                "ParentProcessId": 5678,
                "Name": "copilot.exe",
                "CommandLine": "copilot.exe --resume win-sess-001",
                "CreatedUTC": "2026-02-25T21:14:56.0000000+00:00",
            },
        ]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(procs))

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        assert "win-sess-001" in sessions
        assert sessions["win-sess-001"].pid == 1234

    def test_timestamp_matching_for_no_resume(self):
        procs = [
            {
                "ProcessId": 2000,
                "ParentProcessId": 3000,
                "Name": "copilot.exe",
                "CommandLine": "copilot.exe",
                "CreatedUTC": "2026-02-25T21:14:56.0000000+00:00",
            },
        ]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(procs))

        with (
            patch("src.process_tracker.subprocess.run", return_value=mock_result),
            patch(
                "src.process_tracker._match_process_to_session",
                return_value="ts-matched-win",
            ),
        ):
            sessions = _get_running_sessions_windows()

        assert "ts-matched-win" in sessions
        assert sessions["ts-matched-win"].pid == 2000

    def test_terminal_ancestor_walking(self):
        procs = [
            {
                "ProcessId": 100,
                "ParentProcessId": 200,
                "Name": "copilot.exe",
                "CommandLine": "copilot.exe --resume term-sess",
                "CreatedUTC": "2026-02-25T21:14:56.0000000+00:00",
            },
            {
                "ProcessId": 200,
                "ParentProcessId": 300,
                "Name": "cmd.exe",
                "CommandLine": "cmd.exe",
                "CreatedUTC": "2026-02-25T21:14:00.0000000+00:00",
            },
            {
                "ProcessId": 300,
                "ParentProcessId": 0,
                "Name": "WindowsTerminal.exe",
                "CommandLine": "WindowsTerminal.exe",
                "CreatedUTC": "2026-02-25T21:10:00.0000000+00:00",
            },
        ]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(procs))

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        info = sessions["term-sess"]
        assert info.terminal_pid == 300
        assert info.terminal_name == "WindowsTerminal.exe"

    def test_powershell_failure_returns_empty(self):
        mock_result = MagicMock(returncode=1, stdout="")

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        assert sessions == {}

    def test_empty_output_returns_empty(self):
        mock_result = MagicMock(returncode=0, stdout="")

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        assert sessions == {}

    def test_single_process_json_wrapped(self):
        """PowerShell returns a dict (not list) for a single process."""
        proc = {
            "ProcessId": 500,
            "ParentProcessId": 600,
            "Name": "copilot.exe",
            "CommandLine": "copilot.exe --resume single-sess",
            "CreatedUTC": "2026-02-25T21:14:56.0000000+00:00",
        }
        mock_result = MagicMock(returncode=0, stdout=json.dumps(proc))

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        assert "single-sess" in sessions

    def test_yolo_flag_detected(self):
        procs = [
            {
                "ProcessId": 100,
                "ParentProcessId": 200,
                "Name": "copilot.exe",
                "CommandLine": "copilot.exe --yolo --resume yolo-win",
                "CreatedUTC": "2026-02-25T21:14:56.0000000+00:00",
            },
        ]
        mock_result = MagicMock(returncode=0, stdout=json.dumps(procs))

        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            sessions = _get_running_sessions_windows()

        assert sessions["yolo-win"].yolo is True


# ---------------------------------------------------------------------------
# get_running_sessions (lines 409-437)
# ---------------------------------------------------------------------------


class TestGetRunningSessions:
    """Tests for get_running_sessions() caching and dispatch."""

    def setup_method(self):
        _running_cache.data = {}
        _running_cache.time = 0.0

    def teardown_method(self):
        _running_cache.data = {}
        _running_cache.time = 0.0

    def test_returns_cached_data_within_ttl(self):
        cached_info = ProcessInfo(pid=999)
        _running_cache.data = {"cached-sess": cached_info}
        _running_cache.time = time.monotonic()

        result = get_running_sessions()

        assert "cached-sess" in result
        assert result["cached-sess"].pid == 999

    def test_expired_cache_triggers_refresh(self):
        _running_cache.data = {"old-sess": ProcessInfo(pid=1)}
        _running_cache.time = 0.0  # very old

        with (
            patch("src.process_tracker.sys.platform", "darwin"),
            patch(
                "src.process_tracker._get_running_sessions_unix",
                return_value={"new-sess": ProcessInfo(pid=2)},
            ),
            patch(
                "src.process_tracker._get_session_state",
                return_value=SessionState(
                    state="unknown", waiting_context="", bg_tasks=0, bg_task_list=[]
                ),
            ),
        ):
            result = get_running_sessions()

        assert "new-sess" in result
        assert "old-sess" not in result

    def test_calls_unix_on_non_windows(self):
        with (
            patch("src.process_tracker.sys.platform", "darwin"),
            patch(
                "src.process_tracker._get_running_sessions_unix", return_value={}
            ) as mock_unix,
            patch("src.process_tracker._get_running_sessions_windows") as mock_win,
        ):
            get_running_sessions()

        mock_unix.assert_called_once()
        mock_win.assert_not_called()

    def test_calls_windows_on_win32(self):
        with (
            patch("src.process_tracker.sys.platform", "win32"),
            patch(
                "src.process_tracker._get_running_sessions_windows", return_value={}
            ) as mock_win,
            patch("src.process_tracker._get_running_sessions_unix") as mock_unix,
        ):
            get_running_sessions()

        mock_win.assert_called_once()
        mock_unix.assert_not_called()

    def test_enriches_sessions_with_state(self):
        fake_info = ProcessInfo(pid=100)
        state = SessionState(state="waiting", waiting_context="Pick one", bg_tasks=2, bg_task_list=[])

        with (
            patch("src.process_tracker.sys.platform", "darwin"),
            patch(
                "src.process_tracker._get_running_sessions_unix",
                return_value={"sess-enrich": fake_info},
            ),
            patch("src.process_tracker._get_session_state", return_value=state),
        ):
            result = get_running_sessions()

        assert result["sess-enrich"].state == "waiting"
        assert result["sess-enrich"].waiting_context == "Pick one"
        assert result["sess-enrich"].bg_tasks == 2

    def test_exception_returns_stale_cache(self):
        _running_cache.data = {"stale-sess": ProcessInfo(pid=42)}
        _running_cache.time = 0.0  # expired

        with (
            patch("src.process_tracker.sys.platform", "darwin"),
            patch(
                "src.process_tracker._get_running_sessions_unix",
                side_effect=RuntimeError("ps failed"),
            ),
        ):
            result = get_running_sessions()

        assert "stale-sess" in result


# ---------------------------------------------------------------------------
# _focus_session_window_windows (lines 610-704)
# ---------------------------------------------------------------------------


class TestFocusSessionWindowWindows:
    """Tests for _focus_session_window_windows()."""

    def _make_sessions(self, **kwargs):
        defaults = dict(
            pid=100, parent_pid=200, terminal_pid=300, terminal_name="WindowsTerminal.exe"
        )
        defaults.update(kwargs)
        return {"sess-1": ProcessInfo(**defaults)}

    def test_import_error_returns_false(self):
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions()
        with patch.dict("sys.modules", {"win32gui": None, "win32process": None, "win32con": None}):
            with patch("builtins.__import__", side_effect=ImportError("no win32gui")):
                ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is False
        assert "pywin32" in msg.lower() or "not installed" in msg.lower()

    def test_no_terminal_pid_returns_false(self):
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions(terminal_pid=0)

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()
        mock_subprocess = MagicMock()
        mock_subprocess.return_value = MagicMock(
            returncode=1, stdout=""
        )

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch("src.process_tracker._build_diagnostics", return_value="diag"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is False
        assert "could not find terminal" in msg.lower()

    def test_no_matching_window_returns_false(self):
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions()

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()

        # EnumWindows calls callback but no window matches
        mock_win32gui.EnumWindows = MagicMock(side_effect=lambda cb, _: None)

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch("src.process_tracker._build_diagnostics", return_value="diag"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is False
        assert "no visible window" in msg.lower()

    def test_successful_focus_wt_tab_matched(self):
        """WT focus succeeds when _try_focus_wt_tab finds the right tab."""
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions()

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()
        mock_win32con.SW_SHOWMINIMIZED = 2

        # Simulate EnumWindows finding a matching window
        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)
            mock_win32gui.GetWindowText.return_value = "Terminal Window"
            cb(12345, None)

        mock_win32gui.EnumWindows = fake_enum
        mock_win32gui.GetWindowPlacement.return_value = (0, 1, 0, 0, 0)  # not minimized
        mock_win32gui.GetForegroundWindow.return_value = 99999
        mock_win32process.GetWindowThreadProcessId.side_effect = lambda hwnd: (
            (10, 300) if hwnd == 12345 else (20, 999)
        )
        mock_win32gui.GetWindowText.return_value = "Terminal Window"

        mock_subprocess = MagicMock(return_value=MagicMock(returncode=1, stdout=""))

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch("src.process_tracker.subprocess.run", mock_subprocess),
            patch("src.process_tracker._try_focus_wt_tab", return_value=(12345, "Switched to tab: My Tab")),
            patch("src.process_tracker._bring_hwnd_to_front"),
            patch("src.process_tracker._build_diagnostics", return_value="diag"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is True
        assert "focused" in msg.lower()

    def test_wt_no_tab_match_returns_false(self):
        """WT focus fails gracefully when no tab matches the session."""
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions()

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)
            mock_win32gui.GetWindowText.return_value = "Terminal Window"
            cb(12345, None)

        mock_win32gui.EnumWindows = fake_enum
        mock_win32gui.GetWindowText.return_value = "Terminal Window"
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch("src.process_tracker._try_focus_wt_tab", return_value=(None, "No tab matched")),
            patch("src.process_tracker._bring_hwnd_to_front"),
            patch("src.process_tracker._build_diagnostics", return_value="diag"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is False
        assert "could not identify" in msg.lower()

    def test_non_wt_terminal_focuses_without_tab_matching(self):
        """Non-WT terminals (e.g., Alacritty) skip tab matching entirely."""
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions(terminal_name="alacritty.exe")

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()
        mock_win32con.SW_SHOWMINIMIZED = 2

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)
            mock_win32gui.GetWindowText.return_value = "Alacritty"
            cb(12345, None)

        mock_win32gui.EnumWindows = fake_enum
        mock_win32gui.GetWindowPlacement.return_value = (0, 1, 0, 0, 0)
        mock_win32gui.GetForegroundWindow.return_value = 99999
        mock_win32process.GetWindowThreadProcessId.side_effect = lambda hwnd: (
            (10, 300) if hwnd == 12345 else (20, 999)
        )
        mock_win32gui.GetWindowText.return_value = "Alacritty"

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch("src.process_tracker._bring_hwnd_to_front"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is True
        assert "focused" in msg.lower()

    def test_cached_hwnd_used_first(self):
        """When terminal_hwnd is cached, tries that window first."""
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions(terminal_hwnd=99999)

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()
        mock_win32con.SW_SHOWMINIMIZED = 2
        mock_win32gui.GetWindowText.return_value = "Correct Window"

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch(
                "src.process_tracker._try_focus_wt_tab",
                return_value=(99999, "Switched to tab: My Session"),
            ) as mock_try,
            patch("src.process_tracker._bring_hwnd_to_front") as mock_bring,
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is True
        assert "focused" in msg.lower()
        # Verify _try_focus_wt_tab was called with cached_hwnd
        mock_try.assert_called_once_with(99999, "sess-1", cached_hwnd=99999)
        mock_bring.assert_called_once_with(99999)

    def test_cached_hwnd_fallback_on_failure(self):
        """When cached HWND fails, falls through to full search."""
        from src.process_tracker import _focus_session_window_windows

        sessions = self._make_sessions(terminal_hwnd=99999)

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32con = MagicMock()

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)
            mock_win32gui.GetWindowText.return_value = "Fallback"
            cb(12345, None)

        mock_win32gui.EnumWindows = fake_enum
        mock_win32gui.GetWindowText.return_value = "Fallback"
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 300)

        # First call (cached path) fails, second call (full search) also fails
        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process, "win32con": mock_win32con},
            ),
            patch(
                "src.process_tracker._try_focus_wt_tab",
                side_effect=[(None, ""), (None, "No tab matched")],
            ),
            patch("src.process_tracker._bring_hwnd_to_front"),
            patch("src.process_tracker._build_diagnostics", return_value="diag"),
        ):
            ok, msg = _focus_session_window_windows("sess-1", sessions)
        assert ok is False
        assert "could not identify" in msg.lower()


# ---------------------------------------------------------------------------
# _get_session_match_candidates
# ---------------------------------------------------------------------------


class TestGetSessionMatchCandidates:
    """Tests for _get_session_match_candidates()."""

    def test_returns_intent_then_summary(self):
        from src.process_tracker import _get_session_match_candidates

        with (
            patch(
                "src.process_tracker._read_event_data",
                return_value=MagicMock(intent="Fix the login bug"),
            ),
            patch("src.process_tracker._get_session_summary", return_value="Fix Login Issue"),
        ):
            result = _get_session_match_candidates("sess-1")
        assert result == ["fix the login bug", "fix login issue"]

    def test_returns_only_summary_when_no_intent(self):
        from src.process_tracker import _get_session_match_candidates

        with (
            patch("src.process_tracker._read_event_data", return_value=MagicMock(intent="")),
            patch("src.process_tracker._get_session_summary", return_value="My Summary"),
        ):
            result = _get_session_match_candidates("sess-1")
        assert result == ["my summary"]

    def test_returns_empty_when_nothing_available(self):
        from src.process_tracker import _get_session_match_candidates

        with (
            patch("src.process_tracker._read_event_data", return_value=MagicMock(intent="")),
            patch("src.process_tracker._get_session_summary", return_value=""),
        ):
            result = _get_session_match_candidates("sess-1")
        assert result == []

    def test_deduplicates_identical_intent_and_summary(self):
        from src.process_tracker import _get_session_match_candidates

        with (
            patch(
                "src.process_tracker._read_event_data",
                return_value=MagicMock(intent="Same Text"),
            ),
            patch("src.process_tracker._get_session_summary", return_value="Same Text"),
        ):
            result = _get_session_match_candidates("sess-1")
        assert result == ["same text"]

    def test_handles_event_data_exception(self):
        from src.process_tracker import _get_session_match_candidates

        with (
            patch("src.process_tracker._read_event_data", side_effect=Exception("boom")),
            patch("src.process_tracker._get_session_summary", return_value="Fallback Summary"),
        ):
            result = _get_session_match_candidates("sess-1")
        assert result == ["fallback summary"]


# ---------------------------------------------------------------------------
# _try_focus_wt_tab
# ---------------------------------------------------------------------------


class TestTryFocusWtTab:
    """Tests for _try_focus_wt_tab()."""

    def _make_mock_tab(self, title):
        tab = MagicMock()
        tab.window_text.return_value = title
        tab.iface_selection_item = MagicMock()
        return tab

    def test_matches_tab_by_intent(self):
        from src.process_tracker import _try_focus_wt_tab

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)

        # Simulate EnumWindows returning two WT windows
        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.side_effect = lambda h: {111: "Win1", 222: "Win2"}.get(h, "")
            mock_win32process.GetWindowThreadProcessId.side_effect = lambda h: (1, 500)
            cb(111, None)
            cb(222, None)

        mock_win32gui.EnumWindows = fake_enum

        tab_wrong = self._make_mock_tab("PowerShell")
        tab_right = self._make_mock_tab("🤖 Fixing login bug")

        mock_app_instance = MagicMock()
        mock_window = MagicMock()
        # Window 111 has no match, window 222 has the match
        mock_app_instance.window.side_effect = lambda handle: mock_window
        call_count = [0]

        def fake_descendants(control_type):
            call_count[0] += 1
            if call_count[0] == 1:
                return [tab_wrong]
            return [tab_wrong, tab_right]

        mock_window.descendants = fake_descendants

        mock_app_cls = MagicMock(return_value=mock_app_instance)
        mock_app_instance.connect.return_value = mock_app_instance

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process},
            ),
            patch("src.process_tracker._get_pywinauto_app", return_value=mock_app_cls),
            patch(
                "src.process_tracker._get_session_match_candidates",
                return_value=["fixing login bug"],
            ),
        ):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1")
        assert matched_hwnd == 222
        assert "switched to tab" in msg.lower()
        tab_right.iface_selection_item.Select.assert_called_once()

    def test_no_candidates_returns_none(self):
        from src.process_tracker import _try_focus_wt_tab

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process},
            ),
            patch("src.process_tracker._get_pywinauto_app", return_value=MagicMock()),
            patch("src.process_tracker._get_session_match_candidates", return_value=[]),
        ):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1")
        assert matched_hwnd is None
        assert "no session summary" in msg.lower()

    def test_no_matching_tab_returns_none_with_tried(self):
        from src.process_tracker import _try_focus_wt_tab

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.return_value = "Win1"
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)
            cb(111, None)

        mock_win32gui.EnumWindows = fake_enum

        tab_other = self._make_mock_tab("Unrelated Tab")
        mock_app_instance = MagicMock()
        mock_window = MagicMock()
        mock_window.descendants.return_value = [tab_other]
        mock_app_instance.window.return_value = mock_window
        mock_app_cls = MagicMock(return_value=mock_app_instance)
        mock_app_instance.connect.return_value = mock_app_instance

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process},
            ),
            patch("src.process_tracker._get_pywinauto_app", return_value=mock_app_cls),
            patch(
                "src.process_tracker._get_session_match_candidates",
                return_value=["my session"],
            ),
        ):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1")
        assert matched_hwnd is None
        assert "no tab matched" in msg.lower()
        assert "'my session'" in msg.lower()

    def test_cached_hwnd_tried_first(self):
        from src.process_tracker import _try_focus_wt_tab

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)

        visited_hwnds = []

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.side_effect = lambda h: "Win"
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)
            cb(111, None)
            cb(222, None)

        mock_win32gui.EnumWindows = fake_enum

        tab_match = self._make_mock_tab("🤖 My Session Task")
        mock_app_instance = MagicMock()
        mock_window = MagicMock()
        mock_window.descendants.return_value = [tab_match]
        mock_app_instance.window.return_value = mock_window
        mock_app_cls = MagicMock(return_value=mock_app_instance)
        mock_app_instance.connect.side_effect = lambda handle: (
            visited_hwnds.append(handle) or mock_app_instance
        )

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process},
            ),
            patch("src.process_tracker._get_pywinauto_app", return_value=mock_app_cls),
            patch(
                "src.process_tracker._get_session_match_candidates",
                return_value=["my session task"],
            ),
        ):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1", cached_hwnd=222)
        # cached_hwnd (222) should be tried first
        assert visited_hwnds[0] == 222

    def test_pywinauto_unavailable_returns_none(self):
        from src.process_tracker import _try_focus_wt_tab

        with patch("src.process_tracker._get_pywinauto_app", return_value=None):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1")
        assert matched_hwnd is None

    def test_single_tab_window_skips_select(self):
        """When a window has only one tab, don't call Select()."""
        from src.process_tracker import _try_focus_wt_tab

        mock_win32gui = MagicMock()
        mock_win32process = MagicMock()
        mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)

        def fake_enum(cb, _):
            mock_win32gui.IsWindowVisible.return_value = True
            mock_win32gui.GetWindowText.return_value = "Win"
            mock_win32process.GetWindowThreadProcessId.return_value = (1, 500)
            cb(111, None)

        mock_win32gui.EnumWindows = fake_enum

        tab_match = self._make_mock_tab("🤖 Solo Session")
        mock_app_instance = MagicMock()
        mock_window = MagicMock()
        mock_window.descendants.return_value = [tab_match]  # only 1 tab
        mock_app_instance.window.return_value = mock_window
        mock_app_cls = MagicMock(return_value=mock_app_instance)
        mock_app_instance.connect.return_value = mock_app_instance

        with (
            patch.dict(
                "sys.modules",
                {"win32gui": mock_win32gui, "win32process": mock_win32process},
            ),
            patch("src.process_tracker._get_pywinauto_app", return_value=mock_app_cls),
            patch(
                "src.process_tracker._get_session_match_candidates",
                return_value=["solo session"],
            ),
        ):
            matched_hwnd, msg = _try_focus_wt_tab(111, "sess-1")
        assert matched_hwnd == 111
        tab_match.iface_selection_item.Select.assert_not_called()


# ---------------------------------------------------------------------------
# _focus_session_window_macos (lines 707-742)
# ---------------------------------------------------------------------------


class TestFocusSessionWindowMacos:
    """Tests for _focus_session_window_macos()."""

    def _make_sessions(self, terminal_name="iTerm2", terminal_pid=300):
        return {
            "sess-1": ProcessInfo(
                pid=100, parent_pid=200, terminal_pid=terminal_pid, terminal_name=terminal_name
            )
        }

    def test_osascript_success(self):
        from src.process_tracker import _focus_session_window_macos

        sessions = self._make_sessions(terminal_name="iTerm2")
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("src.process_tracker.subprocess.run", return_value=mock_result) as mock_run:
            ok, msg = _focus_session_window_macos("sess-1", sessions)
        assert ok is True
        assert "iTerm" in msg
        # Verify osascript was called
        call_args = mock_run.call_args[0][0]
        assert "osascript" in call_args

    def test_osascript_failure(self):
        from src.process_tracker import _focus_session_window_macos

        sessions = self._make_sessions(terminal_name="iTerm2")
        mock_result = MagicMock(returncode=1, stderr="script error")
        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            ok, msg = _focus_session_window_macos("sess-1", sessions)
        assert ok is False
        assert "osascript failed" in msg.lower()

    def test_unknown_terminal_falls_back(self):
        from src.process_tracker import _focus_session_window_macos

        sessions = self._make_sessions(terminal_name="UnknownTerminal")
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            ok, msg = _focus_session_window_macos("sess-1", sessions)
        # Should fall back to first MACOS_FALLBACK_TERMINALS entry ("Terminal")
        assert ok is True
        assert "Terminal" in msg

    def test_subprocess_exception(self):
        from src.process_tracker import _focus_session_window_macos

        sessions = self._make_sessions(terminal_name="iTerm2")
        with patch(
            "src.process_tracker.subprocess.run", side_effect=Exception("timeout")
        ):
            ok, msg = _focus_session_window_macos("sess-1", sessions)
        assert ok is False
        assert "could not focus" in msg.lower()

    def test_terminal_app_name_mapping(self):
        from src.process_tracker import _focus_session_window_macos

        # Test that "warp" maps to "Warp"
        sessions = self._make_sessions(terminal_name="warp")
        mock_result = MagicMock(returncode=0, stderr="")
        with patch("src.process_tracker.subprocess.run", return_value=mock_result):
            ok, msg = _focus_session_window_macos("sess-1", sessions)
        assert ok is True
        assert "Warp" in msg


# ---------------------------------------------------------------------------
# focus_session_window (lines 745-758)
# ---------------------------------------------------------------------------


class TestFocusSessionWindow:
    """Tests for focus_session_window() dispatch."""

    def test_session_not_found(self):
        from src.process_tracker import focus_session_window

        with patch("src.process_tracker.get_running_sessions", return_value={}):
            ok, msg = focus_session_window("nonexistent")
        assert ok is False
        assert "not found" in msg.lower()

    def test_dispatches_to_windows(self):
        from src.process_tracker import focus_session_window

        fake = {"sess-1": ProcessInfo(pid=1)}
        with (
            patch("src.process_tracker.get_running_sessions", return_value=fake),
            patch("src.process_tracker.sys.platform", "win32"),
            patch(
                "src.process_tracker._focus_session_window_windows",
                return_value=(True, "ok"),
            ) as mock_win,
        ):
            ok, msg = focus_session_window("sess-1")
        mock_win.assert_called_once()
        assert ok is True

    def test_dispatches_to_macos(self):
        from src.process_tracker import focus_session_window

        fake = {"sess-1": ProcessInfo(pid=1)}
        with (
            patch("src.process_tracker.get_running_sessions", return_value=fake),
            patch("src.process_tracker.sys.platform", "darwin"),
            patch(
                "src.process_tracker._focus_session_window_macos",
                return_value=(True, "focused"),
            ) as mock_mac,
        ):
            ok, msg = focus_session_window("sess-1")
        mock_mac.assert_called_once()
        assert ok is True

    def test_unsupported_platform(self):
        from src.process_tracker import focus_session_window

        fake = {"sess-1": ProcessInfo(pid=1)}
        with (
            patch("src.process_tracker.get_running_sessions", return_value=fake),
            patch("src.process_tracker.sys.platform", "linux"),
        ):
            ok, msg = focus_session_window("sess-1")
        assert ok is False
        assert "not supported" in msg.lower()
