"""parse_sdk_message keeps CLI-synthesized error text out of Vesta's published speech and routes
it to the error channel so a failed turn is never silent in the app."""

from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from conftest import assistant_msg, consuming, make_stream_harness, result_msg
from core.sdk_parsing import parse_sdk_message
from wait_util import wait_for_condition

API_ERROR_TEXT = 'API Error: 500 {"type":"error","error":{"type":"api_error","message":"Internal server error"}}'


@pytest.mark.parametrize(
    "error_text",
    [
        API_ERROR_TEXT,
        "Prompt is too long",
    ],
    ids=["api-error-json-blob", "prompt-too-long"],
)
def test_cli_synthesized_error_text_is_routed_to_the_error_channel_not_published(error_text):
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [TextBlock(error_text)]

    with patch("core.sdk_parsing.logger.warning") as mock_warning:
        texts, thinking_blocks, session_id, error_texts = parse_sdk_message(msg)

    assert texts == []
    assert thinking_blocks == []
    assert session_id is None
    assert error_texts == [error_text]
    mock_warning.assert_called_once()


def test_normal_assistant_text_passes_through_unchanged():
    normal_text = "Prompt is too long? No, the API error you saw earlier is handled now."
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [TextBlock(normal_text)]

    with patch("core.sdk_parsing.logger.warning") as mock_warning:
        texts, thinking_blocks, session_id, error_texts = parse_sdk_message(msg)

    assert texts == [normal_text]
    assert thinking_blocks == []
    assert session_id is None
    assert error_texts == []
    mock_warning.assert_not_called()


@pytest.mark.anyio
async def test_suppressed_cli_error_turn_emits_an_error_event_instead_of_speech():
    """A turn ending in CLI-synthesized error text still reaches the app: no assistant event
    (the raw machinery never renders as Vesta speaking), one error event carrying the failure."""
    state, config, _, emitted, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock(API_ERROR_TEXT)]))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 2, message="consumer never dispatched the error turn")

    events = [sub.get_nowait() for _ in range(sub.qsize())]
    error_events = [e for e in events if e["type"] == "error"]
    assert [e["text"] for e in error_events] == [f"Turn failed upstream: {API_ERROR_TEXT}"]
    assert emitted == []
