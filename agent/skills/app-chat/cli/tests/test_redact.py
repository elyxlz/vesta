"""Tests for the store's secret scrub: it masks real secrets while keeping the JSON blob valid, skips
word-slug false positives on the sk- pattern, and is idempotent over an already-scrubbed blob."""

import json

from app_chat_cli.redact import redact_data


def test_redact_data_masks_a_secret_and_keeps_valid_json():
    data = json.dumps({"type": "user", "text": "token sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"})
    scrubbed = redact_data(data)
    assert scrubbed is not None
    obj = json.loads(scrubbed)  # still valid JSON after the sub
    assert "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in obj["text"]
    assert "[REDACTED]" in obj["text"]
    assert obj["type"] == "user"


def test_redact_data_returns_none_when_clean():
    assert redact_data(json.dumps({"type": "chat", "text": "hi there"})) is None


def test_redact_data_skips_a_word_slug():
    data = json.dumps({"type": "user", "text": "read sk-hynix-raises-full-year-guidance today"})
    assert redact_data(data) is None


def test_redact_data_is_idempotent_over_a_scrubbed_blob():
    data = json.dumps({"type": "user", "text": "token sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"})
    once = redact_data(data)
    assert once is not None
    assert redact_data(once) is None
