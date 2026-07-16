"""Prove the interrupt()/Stop-hook race that over-credits _stops_received.

Bug: interrupt() fires while the Stop hook subprocess is still in flight (50-200ms
window). It sees _stops_received < _turn_index, sends double-Escape, and sets
_stops_received = _turn_index. When the real Stop arrives moments later, on_stop
increments again: _stops_received = _turn_index + 1. The next query() bumps
_turn_index by one, so receive_response() immediately sees _stops_received >= threshold
and returns a bare ResultMessage — the entire response for that turn is silently
swallowed.
"""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from core.cc_sdk.client import ClaudeSDKClient
from core.cc_sdk.messages import AssistantMessage, ClaudeAgentOptions


def _make_client(transcript_path=None):
    options = ClaudeAgentOptions()
    client = ClaudeSDKClient(options=options)
    if transcript_path is not None:
        client._transcript_path = transcript_path
        client._offset = 0
    return client


def _write_assistant_line(path, text: str) -> None:
    obj = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
        "session_id": "test-session",
    }
    with path.open("a") as f:
        f.write(json.dumps(obj) + "\n")


@pytest.mark.anyio
async def test_interrupt_racing_stop_hook_next_turn_is_not_pre_satisfied(tmp_path):
    """After interrupt() races a Stop-hook delivery, the next turn must start with
    _stops_received < _turn_index so that receive_response() actually waits for the
    real response. This test asserts the correct invariant and FAILS because the
    race leaves _stops_received == _turn_index (pre-satisfied), causing the response
    to be silently swallowed.
    """
    transcript = tmp_path / "turn.jsonl"
    transcript.write_text("")
    client = _make_client(transcript)

    # Turn 1 in progress: turn_index=1, stops_received=0 (Stop subprocess in-flight).
    client._turn_index = 1
    client._stops_received = 0

    # interrupt() fires before Stop hook delivers.
    with patch("core.cc_sdk.client.tmux.send_double_escape", new=AsyncMock()):
        await client.interrupt()

    # The real Stop hook now arrives (the subprocess was already in-flight).
    # This is the on_stop handler: _stops_received += 1.
    client._stops_received += 1  # late Stop delivery

    # Turn 2 starts.
    with patch("core.cc_sdk.client.tmux.submit_text", new=AsyncMock()):
        await client.query("hello, turn 2")

    # CORRECT invariant: a freshly-started turn that has not yet completed must have
    # _stops_received < _turn_index, so receive_response() waits for real content.
    # BUG: the race leaves stops_received == turn_index == 2 (pre-satisfied), so
    # receive_response() returns immediately without any response.
    assert client._stops_received < client._turn_index, (
        f"BUG: _stops_received ({client._stops_received}) >= _turn_index ({client._turn_index}) "
        "immediately after starting turn 2 — receive_response() will exit without waiting "
        "for the real response (turn-2 response is silently swallowed)"
    )


@pytest.mark.anyio
async def test_interrupt_racing_stop_swallows_next_turn_response(tmp_path):
    """After the race, receive_response() for turn 2 must yield the actual response
    content. This test asserts that and FAILS because the over-credited stop causes
    receive_response() to exit in ~0.2 s (post-stop drain with 2 empty polls), before
    the 0.5 s delayed response arrives.
    """
    transcript = tmp_path / "turn.jsonl"
    transcript.write_text("")
    client = _make_client(transcript)

    # Reproduce the race.
    client._turn_index = 1
    client._stops_received = 0

    with patch("core.cc_sdk.client.tmux.send_double_escape", new=AsyncMock()):
        await client.interrupt()
    client._stops_received += 1  # late Stop delivery

    with patch("core.cc_sdk.client.tmux.submit_text", new=AsyncMock()):
        await client.query("hello, turn 2")

    # Simulate the TUI generating the turn-2 response with a 0.5 s delay.
    # Without the bug, receive_response() would wait for this content; with the bug
    # it exits after ~0.2 s (2 empty polls * 0.1 s each) and misses the content.
    async def write_response_after_delay():
        await asyncio.sleep(0.5)
        _write_assistant_line(transcript, "turn-2 response content")
        # The Stop hook for turn 2 arrives after the response is written.
        client._stops_received += 1

    writer_task = asyncio.create_task(write_response_after_delay())

    collected: list[object] = [msg async for msg in client.receive_response()]
    await writer_task

    content_messages = [m for m in collected if isinstance(m, AssistantMessage)]

    # A correctly-behaving receive_response() would have waited and yielded this.
    # With the bug it returns early and the content is never consumed.
    assert len(content_messages) == 1, (
        f"BUG: turn-2 response was swallowed — expected 1 AssistantMessage, got: {content_messages}. Collected: {collected}"
    )
