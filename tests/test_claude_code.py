"""Tests for the Claude Code session reader (src/claude_code.py)."""

import json
import os
from unittest.mock import patch

import pytest

from src.claude_code import (
    CREATE_NO_WINDOW,
    SESSION_ID_PREFIX,
    _build_restart_cmd,
    _decode_project_dir,
    _extract_first_prompt_text,
    _extract_session_id_from_cmdline,
    _extract_text_from_content,
    _extract_tool_uses,
    _find_transcript,
    _session_from_transcript,
    get_claude_session_detail,
    get_claude_sessions,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def claude_projects(tmp_path):
    """Create a mock ~/.claude/projects directory with sessions."""
    projects_dir = tmp_path / "projects"
    project = projects_dir / "C--Users-test-myproject"
    project.mkdir(parents=True)

    # sessions-index.json
    index = {
        "version": 1,
        "entries": [
            {
                "sessionId": "aaaa-1111",
                "fullPath": str(project / "aaaa-1111.jsonl"),
                "firstPrompt": "Fix the login bug",
                "summary": "Login Bug Fix",
                "messageCount": 4,
                "created": "2026-02-01T10:00:00Z",
                "modified": "2026-02-01T11:00:00Z",
                "gitBranch": "fix/login",
                "projectPath": "C:\\Users\\test\\myproject",
                "isSidechain": False,
            },
            {
                "sessionId": "bbbb-2222",
                "fullPath": str(project / "bbbb-2222.jsonl"),
                "firstPrompt": "Add unit tests",
                "summary": "",
                "messageCount": 2,
                "created": "2026-02-02T14:00:00Z",
                "modified": "2026-02-02T15:00:00Z",
                "gitBranch": "",
                "projectPath": "C:\\Users\\test\\myproject",
                "isSidechain": False,
            },
        ],
        "originalPath": "C:\\Users\\test\\myproject",
    }
    (project / "sessions-index.json").write_text(json.dumps(index), encoding="utf-8")

    # Transcript for aaaa-1111
    transcript_lines = [
        json.dumps(
            {
                "type": "user",
                "sessionId": "aaaa-1111",
                "message": {"role": "user", "content": "Fix the login bug"},
                "uuid": "u1",
                "timestamp": "2026-02-01T10:00:00Z",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "sessionId": "aaaa-1111",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll fix that for you."},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "src/auth.py"},
                        },
                    ],
                },
                "uuid": "a1",
                "timestamp": "2026-02-01T10:00:05Z",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "sessionId": "aaaa-1111",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t2",
                            "name": "Write",
                            "input": {"file_path": "src/auth.py", "content": "fixed"},
                        },
                    ],
                },
                "uuid": "a2",
                "timestamp": "2026-02-01T10:00:10Z",
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "sessionId": "aaaa-1111",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Done! The bug is fixed."}],
                },
                "uuid": "a3",
                "timestamp": "2026-02-01T10:00:15Z",
            }
        ),
    ]
    (project / "aaaa-1111.jsonl").write_text(
        "\n".join(transcript_lines), encoding="utf-8"
    )

    return str(projects_dir)


# ── get_claude_sessions ──────────────────────────────────────────────────────


class TestGetClaudeSessions:
    def test_returns_sessions_from_index(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            sessions = get_claude_sessions()

        assert len(sessions) == 2

        s1 = next(s for s in sessions if s["id"] == f"{SESSION_ID_PREFIX}aaaa-1111")
        assert s1["summary"] == "Login Bug Fix"
        assert s1["branch"] == "fix/login"
        assert s1["turn_count"] == 4
        assert s1["source"] == "claude"
        assert s1["cwd"] == "C:\\Users\\test\\myproject"
        assert s1["created_at"] == "2026-02-01T10:00:00Z"

    def test_falls_back_to_first_prompt_for_summary(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            sessions = get_claude_sessions()

        s2 = next(s for s in sessions if s["id"] == f"{SESSION_ID_PREFIX}bbbb-2222")
        assert s2["summary"] == "Add unit tests"

    def test_returns_empty_when_no_projects_dir(self, tmp_path):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", str(tmp_path / "nope")):
            assert get_claude_sessions() == []

    def test_restart_cmd_format(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            sessions = get_claude_sessions()

        s1 = next(s for s in sessions if s["id"] == f"{SESSION_ID_PREFIX}aaaa-1111")
        assert "claude --resume aaaa-1111" in s1["restart_cmd"]
        assert 'cd "C:\\Users\\test\\myproject"' in s1["restart_cmd"]

    def test_session_id_prefixed(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            sessions = get_claude_sessions()

        for s in sessions:
            assert s["id"].startswith(SESSION_ID_PREFIX)


# ── get_claude_session_detail ────────────────────────────────────────────────


class TestGetClaudeSessionDetail:
    def test_parses_turns(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            detail = get_claude_session_detail("aaaa-1111")

        turns = detail["turns"]
        assert len(turns) >= 2
        user_turns = [t for t in turns if t["user_message"]]
        assert user_turns[0]["user_message"] == "Fix the login bug"

    def test_parses_tool_counts(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            detail = get_claude_session_detail("aaaa-1111")

        tool_counts = {tc["name"]: tc["count"] for tc in detail["tool_counts"]}
        assert tool_counts.get("Read") == 1
        assert tool_counts.get("Write") == 1

    def test_parses_files(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            detail = get_claude_session_detail("aaaa-1111")

        assert "src/auth.py" in detail["files"]

    def test_unknown_session_returns_empty(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            detail = get_claude_session_detail("nonexistent")

        assert detail["turns"] == []
        assert detail["tool_counts"] == []
        assert detail["files"] == []


# ── _extract_text_from_content ────────────────────────────────────────────────────────────


class TestExtractText:
    def test_string_content(self):
        assert _extract_text_from_content("Hello world") == "Hello world"

    def test_content_blocks(self):
        content = [
            {"type": "text", "text": "Part one."},
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "text", "text": "Part two."},
        ]
        result = _extract_text_from_content(content)
        assert "Part one." in result
        assert "Part two." in result

    def test_meta_messages_skipped(self):
        assert _extract_text_from_content("<local-command-caveat>skip me</local-command-caveat>") == ""
        assert _extract_text_from_content("<command-name>/exit</command-name>") == ""


# ── _extract_tool_uses ───────────────────────────────────────────────────────


class TestExtractToolUses:
    def test_extracts_tool_names(self):
        content = [
            {"type": "tool_use", "name": "Read", "input": {}},
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "name": "Write", "input": {}},
        ]
        assert _extract_tool_uses(content) == ["Read", "Write"]

    def test_returns_empty_for_string(self):
        assert _extract_tool_uses("some text") == []


# ── _build_restart_cmd ───────────────────────────────────────────────────────


class TestBuildRestartCmd:
    def test_with_cwd(self):
        cmd = _build_restart_cmd("abc-123", "/home/user/proj")
        assert cmd == 'cd "/home/user/proj" && claude --resume abc-123'

    def test_without_cwd(self):
        cmd = _build_restart_cmd("abc-123", "")
        assert cmd == "claude --resume abc-123"


# ── _find_transcript ─────────────────────────────────────────────────────────


class TestFindTranscript:
    def test_finds_existing_transcript(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            path = _find_transcript("aaaa-1111")

        assert path is not None
        assert path.endswith("aaaa-1111.jsonl")

    def test_returns_none_for_missing(self, claude_projects):
        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            assert _find_transcript("nonexistent") is None


# ── _extract_session_id_from_cmdline ─────────────────────────────────────────


class TestExtractSessionIdFromCmdline:
    def test_session_id_flag(self):
        cmd = '"claude.exe" --session-id abc-123 --mcp-config foo.json'
        assert _extract_session_id_from_cmdline(cmd) == "abc-123"

    def test_resume_flag(self):
        cmd = "claude --resume def-456"
        assert _extract_session_id_from_cmdline(cmd) == "def-456"

    def test_quoted_id(self):
        cmd = 'claude --session-id "ghi-789" --other flag'
        assert _extract_session_id_from_cmdline(cmd) == "ghi-789"

    def test_no_session_flag(self):
        cmd = "claude --help"
        assert _extract_session_id_from_cmdline(cmd) is None

    def test_session_id_preferred_over_resume(self):
        cmd = "claude --session-id first-id --resume second-id"
        assert _extract_session_id_from_cmdline(cmd) == "first-id"


# ── _decode_project_dir ──────────────────────────────────────────────────────


class TestDecodeProjectDir:
    def test_windows_path(self):
        with patch("src.claude_code.sys") as mock_sys:
            mock_sys.platform = "win32"
            result = _decode_project_dir("C--Users-jeffstei-myproject")
        assert result == "C:\\Users\\jeffstei\\myproject"

    def test_unix_path(self):
        with patch("src.claude_code.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = _decode_project_dir("home-user-projects-myapp")
        assert result == "/home/user/projects/myapp"


# ── _extract_first_prompt_text ───────────────────────────────────────────────


class TestExtractFirstPromptText:
    def test_nested_message_content(self):
        msg = {"message": {"role": "user", "content": "Fix the bug"}}
        assert _extract_first_prompt_text(msg) == "Fix the bug"

    def test_content_blocks(self):
        msg = {
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": "Hello there"}],
            }
        }
        assert _extract_first_prompt_text(msg) == "Hello there"

    def test_falls_back_to_top_level_content(self):
        msg = {"content": "Top level text"}
        assert _extract_first_prompt_text(msg) == "Top level text"

    def test_empty_message(self):
        assert _extract_first_prompt_text({}) == ""


# ── _session_from_transcript ─────────────────────────────────────────────────


class TestSessionFromTranscript:
    def test_parses_transcript(self, claude_projects):
        jsonl_path = os.path.join(claude_projects, "C--Users-test-myproject", "aaaa-1111.jsonl")
        result = _session_from_transcript("aaaa-1111", jsonl_path, "C:\\Users\\test\\myproject", None)

        assert result is not None
        assert result["id"] == f"{SESSION_ID_PREFIX}aaaa-1111"
        assert result["summary"] == "Fix the login bug"
        assert result["source"] == "claude"
        assert result["is_running"] is False
        assert result["turn_count"] > 0

    def test_missing_file_returns_none(self, tmp_path):
        result = _session_from_transcript("nope", str(tmp_path / "nope.jsonl"), "/tmp", None)
        assert result is None

    def test_with_running_process(self, claude_projects):
        from src.models import ProcessInfo

        proc = ProcessInfo(pid=999, state="idle", waiting_context="Waiting")
        jsonl_path = os.path.join(claude_projects, "C--Users-test-myproject", "aaaa-1111.jsonl")
        result = _session_from_transcript("aaaa-1111", jsonl_path, "/tmp", proc)

        assert result["is_running"] is True
        assert result["state"] == "idle"


# ── Unindexed JSONL discovery ────────────────────────────────────────────────


class TestUnindexedSessionDiscovery:
    def test_discovers_unindexed_jsonl(self, claude_projects):
        """Sessions with JSONL files but not in sessions-index.json are found."""
        project = os.path.join(claude_projects, "C--Users-test-myproject")
        # Create an unindexed transcript
        unindexed = [
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "Unindexed session prompt"},
                "timestamp": "2026-03-01T12:00:00Z",
            }),
            json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "OK"}]},
                "timestamp": "2026-03-01T12:00:05Z",
            }),
        ]
        with open(os.path.join(project, "cccc-3333.jsonl"), "w", encoding="utf-8") as f:
            f.write("\n".join(unindexed))

        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", claude_projects):
            sessions = get_claude_sessions()

        assert len(sessions) == 3  # 2 indexed + 1 unindexed
        unindexed_session = next(s for s in sessions if s["id"] == f"{SESSION_ID_PREFIX}cccc-3333")
        assert unindexed_session["summary"] == "Unindexed session prompt"
        assert unindexed_session["source"] == "claude"

    def test_no_index_file_still_finds_jsonl(self, tmp_path):
        """Project dir with no sessions-index.json still discovers JSONL files."""
        projects_dir = tmp_path / "projects"
        project = projects_dir / "D--work-repo"
        project.mkdir(parents=True)
        transcript = [
            json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "Hello"},
                "timestamp": "2026-03-01T12:00:00Z",
            }),
        ]
        (project / "dddd-4444.jsonl").write_text("\n".join(transcript), encoding="utf-8")

        with patch("src.claude_code.CLAUDE_PROJECTS_DIR", str(projects_dir)):
            sessions = get_claude_sessions()

        assert len(sessions) == 1
        assert sessions[0]["id"] == f"{SESSION_ID_PREFIX}dddd-4444"


# ── Process state defaults ───────────────────────────────────────────────────


class TestProcessStateDefaults:
    def test_windows_process_defaults_to_idle(self):
        """Claude processes detected on Windows should default to idle state."""
        from src.claude_code import _get_running_claude_windows

        fake_ps_output = json.dumps([
            {
                "ProcessId": 12345,
                "ParentProcessId": 100,
                "Name": "claude.exe",
                "CommandLine": "claude.exe --session-id test-session-1",
                "CreatedUTC": "2026-03-02T10:00:00Z",
            },
        ])
        with patch("src.claude_code.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = fake_ps_output
            result = _get_running_claude_windows()

        assert f"{SESSION_ID_PREFIX}test-session-1" in result
        proc = result[f"{SESSION_ID_PREFIX}test-session-1"]
        assert proc.state == "idle"
        assert "waiting for user message" in proc.waiting_context

    def test_windows_process_scan_uses_hidden_window(self):
        """Claude process scans should not flash PowerShell windows."""
        from src.claude_code import _get_running_claude_windows

        with (
            patch("src.claude_code.sys.platform", "win32"),
            patch("src.claude_code.subprocess.run") as mock_run,
        ):
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "[]"
            _get_running_claude_windows()

        assert mock_run.call_args.kwargs["creationflags"] == CREATE_NO_WINDOW
