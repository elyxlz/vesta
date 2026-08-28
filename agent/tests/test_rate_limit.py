"""A rejected rate limit is surfaced from the SDK's structured classification, never the CLI's
paraphrase (which has misreported a five_hour rejection as a "monthly spend limit", issue #1071)."""

import pytest
from claude_agent_sdk import RateLimitEvent, RateLimitInfo, RateLimitStatus, RateLimitType, TextBlock
from conftest import assistant_msg, consuming, make_stream_harness, result_msg
from wait_util import wait_for_condition

from core.sdk_parsing import rate_limit_notice
from core.state_store import RateLimitedWindow

NOW = 1_000_000.0


@pytest.mark.parametrize(
    "info,expected",
    [
        (
            RateLimitInfo(status="rejected", rate_limit_type="five_hour", resets_at=int(NOW) + 12_000),
            (
                "Claude rate limit hit: the 5-hour usage window is exhausted, resets in 3h 20m. "
                "This is the rolling usage limit, not a spend or billing limit."
            ),
        ),
        (
            RateLimitInfo(status="rejected", rate_limit_type="seven_day"),
            "Claude rate limit hit: the weekly usage window is exhausted. This is the rolling usage limit, not a spend or billing limit.",
        ),
        (
            RateLimitInfo(status="rejected", rate_limit_type="seven_day_opus"),
            "Claude rate limit hit: the weekly Opus usage window is exhausted. This is the rolling usage limit, not a spend or billing limit.",
        ),
        (
            RateLimitInfo(status="rejected", rate_limit_type="seven_day_sonnet"),
            (
                "Claude rate limit hit: the weekly Sonnet usage window is exhausted. "
                "This is the rolling usage limit, not a spend or billing limit."
            ),
        ),
        (
            RateLimitInfo(status="rejected", rate_limit_type="overage", resets_at=int(NOW) + 1_500),
            "Claude rate limit hit: the extra usage budget is exhausted, resets in 25m.",
        ),
        (
            RateLimitInfo(status="rejected", resets_at=int(NOW) + 1_500),
            "Claude rate limit hit, resets in 25m.",
        ),
        (
            RateLimitInfo(status="rejected", rate_limit_type="five_hour", resets_at=int(NOW) - 60),
            "Claude rate limit hit: the 5-hour usage window is exhausted. This is the rolling usage limit, not a spend or billing limit.",
        ),
    ],
)
def test_rejected_rate_limit_wording_comes_from_the_structured_classification(info, expected):
    assert rate_limit_notice(info, now=NOW) == expected


@pytest.mark.parametrize("status", ["allowed", "allowed_warning"])
def test_non_rejected_rate_limit_produces_no_notice(status):
    info = RateLimitInfo(status=status, rate_limit_type="five_hour", utilization=0.9)
    assert rate_limit_notice(info, now=NOW) is None


def _rate_limit_event(status: RateLimitStatus, *, rate_limit_type: RateLimitType = "five_hour", resets_at: int | None = None) -> RateLimitEvent:
    info = RateLimitInfo(status=status, rate_limit_type=rate_limit_type, resets_at=resets_at)
    return RateLimitEvent(rate_limit_info=info, uuid="u1", session_id="s1")


def _rate_limited_events(sub) -> list[dict]:
    events = [sub.get_nowait() for _ in range(sub.qsize())]
    return [e for e in events if e["type"] == "rate_limited"]


@pytest.mark.anyio
async def test_rejected_rate_limit_emits_one_rate_limited_event_per_window():
    """The rejection reaches the event stream as an authoritative rate_limited event carrying the
    structured classification; retries hitting the same window are not repeated, a later distinct
    window is."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(_rate_limit_event("rejected", resets_at=3_000_000))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 4, message="consumer never dispatched the rate limit events")

    events = _rate_limited_events(sub)
    assert [e["resets_at"] for e in events] == [2_000_000, 3_000_000]
    assert all(e["window"] == "five_hour" for e in events)
    assert all("5-hour usage window" in e["text"] for e in events)
    assert all("monthly" not in e["text"] for e in events)


@pytest.mark.anyio
async def test_allowed_rate_limit_event_emits_nothing():
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("allowed"))
        await message_queue.put(_rate_limit_event("allowed_warning"))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 3, message="consumer never dispatched the rate limit events")

    assert _rate_limited_events(sub) == []


CLI_LIMIT_PARAPHRASE = "You've hit your monthly spend limit · raise it at claude.ai/settings/usage?from=cc_cli_limit_message"
API_ERROR_429 = 'API Error: 429 {"type":"error","error":{"type":"rate_limit_error","message":"You have reached your monthly limit"}}'


@pytest.mark.anyio
async def test_cli_limit_paraphrase_is_suppressed_and_marks_rate_limited():
    """The CLI reprints its own paraphrase of a rejection on every scheduled retry, as a plain
    assistant text (no companion RateLimitEvent, observed on live agents 2026-08-27). It is not
    Vesta's speech and its wording is untrusted (issue #1071): the stream marks the agent rate
    limited once and publishes nothing else."""
    state, config, _, emitted, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock(CLI_LIMIT_PARAPHRASE)]))
        await message_queue.put(assistant_msg([TextBlock(CLI_LIMIT_PARAPHRASE)]))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 3, message="consumer never dispatched the paraphrase")

    assert emitted == []
    events = _rate_limited_events(sub)
    assert [e["window"] for e in events] == [None]
    assert "monthly" not in events[0]["text"]
    assert state.persisted.rate_limited == RateLimitedWindow(window=None, resets_at=None)


@pytest.mark.anyio
async def test_api_error_429_text_marks_rate_limited_not_error():
    """An `API Error: 429` body is a rate-limit rejection, not a generic turn failure: it reaches
    the stream as one rate_limited event and never as the error channel's "hit a snag"."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock(API_ERROR_429)]))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 2, message="consumer never dispatched the error text")

    events = [sub.get_nowait() for _ in range(sub.qsize())]
    assert [e["type"] for e in events if e["type"] in ("rate_limited", "error")] == ["rate_limited"]
    assert state.persisted.rate_limited is not None


@pytest.mark.anyio
async def test_result_429_status_marks_rate_limited():
    """A ResultMessage carrying api_error_status=429 is the rejection's last observable shape when
    no text or structured event accompanied it; it marks the state on its own."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 1, message="consumer never dispatched the result")

    assert [e["window"] for e in _rate_limited_events(sub)] == [None]
    assert state.persisted.rate_limited == RateLimitedWindow(window=None, resets_at=None)


@pytest.mark.anyio
async def test_generic_signal_never_downgrades_a_windowed_rate_limit():
    """The structured classification carries the window and reset; the CLI's paraphrase and a bare
    429 carry neither. Once a window is recorded, the generic signals are repeats of it: no second
    event, and the recorded window survives."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(assistant_msg([TextBlock(CLI_LIMIT_PARAPHRASE)]))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 3, message="consumer never dispatched the batch")

    assert [e["window"] for e in _rate_limited_events(sub)] == ["five_hour"]
    assert state.persisted.rate_limited == RateLimitedWindow(window="five_hour", resets_at=2_000_000)


@pytest.mark.anyio
async def test_clean_result_clears_rate_limited_and_a_later_rejection_reports_again():
    """A turn that completes without error is the proof the limit no longer binds: the state clears,
    and a later rejection of the same window is a fresh episode, reported again."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 3, message="consumer never dispatched the clean result")
        assert state.persisted.rate_limited is None
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 5, message="consumer never dispatched the second rejection")

    assert [e["resets_at"] for e in _rate_limited_events(sub)] == [2_000_000, 2_000_000]


@pytest.mark.anyio
async def test_persisted_window_survives_restart_and_stays_silent():
    """The recorded window is persisted state: after a restart the same rejection is the same news,
    so the re-reported window emits nothing (the double notification observed on issue #1071)."""
    state, config, _, _, message_queue, consumed = make_stream_harness()
    state.persisted.rate_limited = RateLimitedWindow(window="five_hour", resets_at=2_000_000)
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("rejected", resets_at=2_000_000))
        await message_queue.put(result_msg(is_error=True, api_error_status=429))
        await wait_for_condition(lambda: len(consumed) >= 2, message="consumer never dispatched the rejection")

    assert _rate_limited_events(sub) == []
