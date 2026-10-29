"""The mail-read boundary must not hand a permanent identifier to the agent.

Positive controls matter more than negative ones here. A masker whose pattern
never matches passes every "this ordinary text is untouched" assertion while
doing nothing at all, and that failure is invisible: output looks identical to
correct behaviour. So every negative case below is paired with a positive.
"""

import pytest
from google_cli.redaction import NI_PLACEHOLDER, mask_identifiers

VALID_NI = [
    ("plain", "my ni is AB123456C ok"),
    ("spaced", "HMRC prints AB 12 34 56 C here"),
    ("second letter T", "ref JT123456B."),
    ("spaced, different prefix", "SE 11 22 33 B"),
]

NOT_NI = [
    # QQ is reserved and never allocated; it is the documented placeholder, so
    # masking it would be a false positive on the very string HMRC prints in
    # examples.
    ("reserved QQ prefix", "QQ123456A"),
    ("first letter D is unallocated", "DA123456A"),
    ("second letter O is unallocated", "AO123456A"),
    ("suffix must be A to D", "AB123456E"),
    ("lowercase is prose, not an identifier", "ab123456c"),
    ("embedded in a longer token", "xAB123456Cx"),
    ("dates in ordinary prose", "meeting 12 05 26 A block"),
]


@pytest.mark.parametrize("label,text", VALID_NI)
def test_masks_valid_national_insurance_numbers(label, text):
    out = mask_identifiers(text)
    assert out != text, f"{label}: value passed through unmasked"
    assert NI_PLACEHOLDER in out
    assert "123456" not in out and "11 22 33" not in out


@pytest.mark.parametrize("label,text", NOT_NI)
def test_leaves_non_identifiers_alone(label, text):
    assert mask_identifiers(text) == text, label


def test_is_idempotent():
    once = mask_identifiers("x AB123456C y")
    assert mask_identifiers(once) == once


def test_handles_empty_and_non_string():
    assert mask_identifiers("") == ""
    assert mask_identifiers(None) is None


def test_masks_every_occurrence_not_just_the_first():
    out = mask_identifiers("first AB123456C then JT123456B")
    assert out.count(NI_PLACEHOLDER) == 2


def test_snapshot_parser_masks_the_snippet_it_returns():
    """The unit above proves the masker works; this proves it is actually WIRED.

    A masking helper that nothing calls passes its own tests forever.
    """
    from google_cli.gmail import _parse_message_snapshot

    msg = {
        "id": "abc",
        "threadId": "t1",
        "payload": {"headers": [{"name": "Subject", "value": "Profile approved"}]},
        "snippet": "Your reference AB123456C has been approved",
        "labelIds": ["INBOX"],
    }
    out = _parse_message_snapshot(msg)
    assert out["subject"] == "Profile approved"  # control: parsing still works
    assert NI_PLACEHOLDER in out["snippet"]
    assert "AB123456C" not in out["snippet"]
