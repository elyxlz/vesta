"""Tests for tool formatting, agent input parsing, and output helpers."""

import datetime as dt

import pytest
from core.client import (
    _contains_dashes,
    _format_tool_call,
    _format_search_results,
    _parse_agent_input,
    _parse_sdk_message,
    _tool_summary,
    filter_tool_lines,
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


@pytest.mark.parametrize("tool_name,agent_type", [("Task", "test-agent"), ("Agent", "code-agent")])
def test_format_tool_call_task_and_agent(tool_name, agent_type):
    formatted, context = _format_tool_call(
        tool_name,
        input_data={"subagent_type": agent_type, "description": "do something"},
        sub_agent_context=None,
    )
    assert "[TASK]" in formatted
    assert agent_type in formatted
    assert context == agent_type


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
    from core.client import _build_query

    result = _build_query(text, timestamp=dt.datetime(2025, 6, 15, 12, 0, 0))
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


def test_parse_sdk_message_extracts_thinking_blocks():
    from unittest.mock import MagicMock

    from claude_agent_sdk import AssistantMessage, TextBlock, ThinkingBlock

    msg = MagicMock(spec=AssistantMessage)
    msg.content = [ThinkingBlock("step one\nstep two", "sig-123"), TextBlock("done")]

    texts, thinking_blocks, context, session_id, has_tool_use = _parse_sdk_message(msg, sub_agent_context=None)

    assert texts == ["done"]
    assert len(thinking_blocks) == 1
    assert thinking_blocks[0].thinking == "step one\nstep two"
    assert thinking_blocks[0].signature == "sig-123"
    assert context is None
    assert session_id is None
    assert has_tool_use is False


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


# --- Search results formatting ---


def test_format_search_results():
    assert _format_search_results([]) == "No results found."

    results = [{"timestamp": "2025-01-01T10:00:00", "role": "user", "content": "hello"}]
    formatted = _format_search_results(results)
    assert "hello" in formatted
    assert "user" in formatted
