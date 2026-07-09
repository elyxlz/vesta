"""parse_sdk_message keeps CLI-synthesized error text out of Vesta's published speech."""

from unittest.mock import MagicMock, patch

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock
from core.sdk_parsing import parse_sdk_message


@pytest.mark.parametrize(
    "error_text",
    [
        'API Error: 500 {"type":"error","error":{"type":"api_error","message":"Internal server error"}}',
        "Prompt is too long",
    ],
    ids=["api-error-json-blob", "prompt-too-long"],
)
def test_cli_synthesized_error_text_is_logged_not_published(error_text):
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [TextBlock(error_text)]

    with patch("core.sdk_parsing.logger.warning") as mock_warning:
        texts, thinking_blocks, session_id = parse_sdk_message(msg)

    assert texts == []
    assert thinking_blocks == []
    assert session_id is None
    mock_warning.assert_called_once()


def test_normal_assistant_text_passes_through_unchanged():
    normal_text = "Prompt is too long? No, the API error you saw earlier is handled now."
    msg = MagicMock(spec=AssistantMessage)
    msg.content = [TextBlock(normal_text)]

    with patch("core.sdk_parsing.logger.warning") as mock_warning:
        texts, thinking_blocks, session_id = parse_sdk_message(msg)

    assert texts == [normal_text]
    assert thinking_blocks == []
    assert session_id is None
    mock_warning.assert_not_called()
