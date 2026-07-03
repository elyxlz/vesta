"""Tests for the live chat-reply preview extractor (stream_preview.py)."""

import json

import pytest

from core.stream_preview import extract_chat_preview


def _bash_input_json(command: str) -> str:
    return json.dumps({"command": command})


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The common shapes googe actually produces.
        (_bash_input_json('app-chat send -m "hey, on it"'), "hey, on it"),
        (_bash_input_json("app-chat send --message 'single quoted'"), "single quoted"),
        (_bash_input_json('sleep 4; app-chat send -m "second message"'), "second message"),
        # Chained sends preview the last one.
        (_bash_input_json('app-chat send -m "first"; app-chat send -m "second"'), "second"),
        # Shell escapes inside double quotes.
        (_bash_input_json('app-chat send -m "she said \\"hi\\""'), 'she said "hi"'),
        # JSON escapes in the command string (newlines in the message).
        (_bash_input_json('app-chat send -m "line one\nline two"'), "line one\nline two"),
        # Not a chat send: no preview.
        (_bash_input_json("ls -la /tmp"), None),
        (_bash_input_json("app-chat history --limit 5"), None),
        # Other keys before command: still found once command streams.
        (json.dumps({"description": "reply", "command": 'app-chat send -m "yo"'}), "yo"),
    ],
)
def test_complete_inputs(raw, expected):
    assert extract_chat_preview(raw) == expected


def test_streams_incrementally():
    """The preview grows chunk by chunk as the tool input streams."""
    full = _bash_input_json('app-chat send -m "hello there, world"')
    seen: list[str | None] = []
    for cut in range(0, len(full) + 1, 3):
        seen.append(extract_chat_preview(full[:cut]))
    # None until the opening quote has streamed, then a growing prefix, ending complete.
    non_null = [s for s in seen if s is not None]
    assert non_null, "preview never appeared"
    assert non_null[-1] == "hello there, world"
    for earlier, later in zip(non_null, non_null[1:]):
        assert later.startswith(earlier), f"preview must only grow: {earlier!r} -> {later!r}"


def test_partial_json_escape_at_chunk_boundary():
    """A chunk ending mid-escape must not corrupt the preview (decode stops at the boundary)."""
    full = _bash_input_json('app-chat send -m "before\\after"')  # \\ in json = one backslash
    # Cut right after the lone backslash inside the JSON string.
    cut = full.index("\\\\") + 1
    partial = extract_chat_preview(full[:cut])
    assert partial == "before" or partial is None


def test_incomplete_unicode_escape_is_deferred():
    raw = '{"command": "app-chat send -m \\"caf\\u00'
    assert extract_chat_preview(raw) in ("caf", None)
    raw_done = '{"command": "app-chat send -m \\"caf\\u00e9'
    assert extract_chat_preview(raw_done) == "café"


def test_message_capped_at_closing_quote():
    """Trailing command text after the closing quote never leaks into the preview."""
    raw = _bash_input_json('app-chat send -m "done" && echo ok')
    assert extract_chat_preview(raw) == "done"
