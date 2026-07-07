"""Tests for tool formatting, agent input parsing, and output helpers."""

import datetime as dt

import pytest
from core.client import _contains_dashes
from core.sdk_parsing import (
    _parse_agent_input,
    _tool_summary,
    filter_tool_lines,
    parse_sdk_message,
)


# --- Agent input parsing ---


@pytest.mark.parametrize(
    "input_data,expected",
    [
        ({"subagent_type": "browser", "description": "open page"}, ("browser", "open page")),
        ({"other": "data"}, ("unknown", "")),
        ("some string", ("unknown", "")),
    ],
    ids=["dict-with-fields", "dict-missing-fields", "non-dict"],
)
def test_parse_agent_input(input_data, expected):
    assert _parse_agent_input(input_data) == expected


# --- Tool summary ---


@pytest.mark.parametrize(
    "tool_name,input_data,expected",
    [
        ("Agent", {"subagent_type": "research", "description": "find docs"}, "Task [research]: find docs"),
        ("Task", {"subagent_type": "code", "description": "write code"}, "Task [code]: write code"),
    ],
)
def test_tool_summary(tool_name, input_data, expected):
    assert _tool_summary(tool_name, input_data) == expected


# --- Build query ---


@pytest.mark.parametrize(
    "text,expect_timestamp",
    [
        ("/compact", False),
        ("/clear some args", False),
        ("hello world", True),
    ],
    ids=["slash-command", "slash-command-with-args", "normal-message"],
)
def test_build_query(text, expect_timestamp):
    from core.sdk_parsing import build_query

    result = build_query(text, timestamp=dt.datetime(2025, 6, 15, 12, 0, 0))
    if expect_timestamp:
        assert "[Current time:" in result
        assert text in result
    else:
        assert result == text


# --- Filter tool lines ---


@pytest.mark.parametrize(
    "input_text,expected",
    [
        ("hello world", "hello world"),
        ("[TOOL] Bash: ls\nthe result", "the result"),
        ("[TASK] [browser]: search\nfound it", "found it"),
        ("[TOOL] done\n[TASK] done", ""),
        ("line one\n  \nline two", "line one\nline two"),
        ("", ""),
    ],
)
def test_filter_tool_lines(input_text, expected):
    assert filter_tool_lines(input_text) == expected


# --- Em/en dash detection ---


def test_contains_dashes_detects_em_dash():
    assert _contains_dashes(["hello \u2014 world"]) is True


def test_contains_dashes_detects_en_dash():
    assert _contains_dashes(["hello \u2013 world"]) is True


def test_contains_dashes_detects_space_dash_space():
    assert _contains_dashes(["hello - world"]) is True


def test_contains_dashes_clean_text():
    assert _contains_dashes(["hello-world"]) is False
    assert _contains_dashes(["just normal text"]) is False
    assert _contains_dashes([]) is False


def test_contains_dashes_multiple_texts():
    assert _contains_dashes(["clean", "also clean"]) is False
    assert _contains_dashes(["clean", "has \u2014 dash"]) is True


# --- SDK message parsing ---


def test_parse_sdk_message_extracts_thinking_blocks_and_ignores_tool_use():
    from unittest.mock import MagicMock

    from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock, ToolUseBlock

    msg = MagicMock(spec=AssistantMessage)
    msg.content = [
        ThinkingBlock("step one\nstep two", "sig-123"),
        ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
        TextBlock("done"),
    ]

    texts, thinking_blocks, session_id = parse_sdk_message(msg)

    # Tool-use blocks contribute no text/thinking: tool activity is surfaced via hooks.
    assert texts == ["done"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0].thinking == "step one\nstep two"
    assert thinking_blocks[0].signature == "sig-123"
    assert session_id is None


def test_parse_sdk_message_returns_session_id_from_result():
    from claude_agent_sdk import ResultMessage

    msg = ResultMessage(subtype="success", duration_ms=100, duration_api_ms=80, is_error=False, num_turns=1, session_id="sess-abc")
    texts, thinking_blocks, session_id = parse_sdk_message(msg)

    assert texts == []
    assert thinking_blocks == []
    assert session_id == "sess-abc"


def test_parse_sdk_message_returns_session_id_from_init():
    """The init message carries the session_id first; parse must return it so the caller persists
    it immediately (resume survives a first-turn crash before any ResultMessage)."""
    from claude_agent_sdk import SystemMessage

    msg = SystemMessage(subtype="init", data={"session_id": "sess-abc-123", "slash_commands": ["compact"]})

    texts, thinking_blocks, session_id = parse_sdk_message(msg)

    assert session_id == "sess-abc-123"
    assert texts == []


def test_parse_sdk_message_skips_thinking_tokens_system_message():
    """thinking_tokens is a per-delta streaming counter the SDK emits dozens of times per turn;
    parse must drop it without logging so it does not flood the agent log."""
    from unittest.mock import patch

    from claude_agent_sdk import SystemMessage

    msg = SystemMessage(subtype="thinking_tokens", data={"estimated_tokens": 312, "estimated_tokens_delta": 5})

    with patch("core.sdk_parsing.logger.system") as mock_system:
        texts, thinking_blocks, session_id = parse_sdk_message(msg)

    mock_system.assert_not_called()
    assert texts == []
    assert thinking_blocks == []
    assert session_id is None


def test_process_message_always_streams():
    """process_message must always pass show_output=True -- regression guard."""
    import ast
    import inspect

    from core.client import process_message

    source = inspect.getsource(process_message)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "show_output":
            val = node.value
            assert isinstance(val, ast.Constant) and val.value is True, (
                f"process_message must pass show_output=True to converse(), found show_output={ast.dump(val)}"
            )
