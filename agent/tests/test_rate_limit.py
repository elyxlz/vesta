"""A rejected rate limit is surfaced from the SDK's structured classification, never the CLI's
paraphrase (which has misreported a five_hour rejection as a "monthly spend limit", issue #1071)."""

import pytest
from claude_agent_sdk import RateLimitEvent, RateLimitInfo, RateLimitStatus, RateLimitType
from conftest import consuming, make_stream_harness, result_msg
from pydantic import SecretStr
from wait_util import wait_for_condition

import core.config as cfg
from core.client import _note_rate_limit
from core.model_access import clear_model_access
from core.provider import ProviderAuthState, ProviderCooldown, ProviderStatus
from core.sdk_parsing import rate_limit_notice

NOW = 1_000_000.0


@pytest.mark.parametrize(
    "info,expected",
    [
        (
            RateLimitInfo(status="rejected", rate_limit_type="five_hour", resets_at=int(NOW) + 12_000),
            "Claude rate limit hit: the 5-hour usage window is exhausted, resets in 3h 20m. "
            "This is the rolling usage limit, not a spend or billing limit.",
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
            "Claude rate limit hit: the weekly Sonnet usage window is exhausted. "
            "This is the rolling usage limit, not a spend or billing limit.",
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
        await message_queue.put(_rate_limit_event("rejected", resets_at=4_000_000_000))
        await message_queue.put(_rate_limit_event("rejected", resets_at=4_000_000_000))
        await message_queue.put(_rate_limit_event("rejected", resets_at=4_000_001_000))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 4, message="consumer never dispatched the rate limit events")

    events = _rate_limited_events(sub)
    assert [e["resets_at"] for e in events] == [4_000_000_000, 4_000_001_000]
    assert all(e["window"] == "five_hour" for e in events)
    assert all("5-hour usage window" in e["text"] for e in events)
    assert all("monthly" not in e["text"] for e in events)
    assert state.persisted.provider_cooldown is not None
    assert state.persisted.provider_cooldown.until == 4_000_001_000
    assert state.persisted.provider_cooldown.window == "five_hour"


@pytest.mark.anyio
async def test_rejected_rate_limit_publishes_cooling_down_model_access():
    state, config, _, _, message_queue, consumed = make_stream_harness()
    sub = state.event_bus.subscribe()

    async with consuming(state, config):
        await message_queue.put(_rate_limit_event("rejected", resets_at=4_000_000_000))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) >= 2, message="consumer never dispatched the rate limit event")

    events = [sub.get_nowait() for _ in range(sub.qsize())]
    access = [event for event in events if event["type"] == "model_access"]
    assert len(access) == 1
    assert access[0]["state"] == "cooling_down"
    assert access[0]["reason"] == "rate_limit"
    assert access[0]["until"] == 4_000_000_000
    assert access[0]["window"] == "five_hour"


@pytest.mark.anyio
async def test_claude_window_event_is_not_applied_to_compatible_key_providers():
    state, config, *_ = make_stream_harness()
    config.provider = cfg.ZaiConfig(key=SecretStr("test-key"), model="glm-5")
    state.provider_status = ProviderStatus(
        state=ProviderAuthState.AUTHENTICATED,
        kind="zai",
        model="glm-5",
    )
    sub = state.event_bus.subscribe()

    await _note_rate_limit(
        _rate_limit_event("rejected", resets_at=4_000_000_000),
        state=state,
        config=config,
    )

    assert state.persisted.provider_cooldown is None
    assert sub.empty()


@pytest.mark.anyio
async def test_provider_change_clears_persisted_cooldown(config, state):
    state.persisted.provider_cooldown = ProviderCooldown(until=4_000_000_000, window="five_hour")
    state.current_turn_rate_limited = True
    sub = state.event_bus.subscribe()

    await clear_model_access(state=state, config=config)

    assert state.persisted.provider_cooldown is None
    assert state.current_turn_rate_limited is False
    event = sub.get_nowait()
    assert event["type"] == "model_access"
    assert event["state"] == "available"


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
