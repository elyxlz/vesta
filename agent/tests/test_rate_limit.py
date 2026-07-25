"""A rejected rate limit is surfaced from the SDK's structured classification, never the CLI's
paraphrase (which has misreported a five_hour rejection as a "monthly spend limit", issue #1071)."""

import asyncio
import time

import pytest
from claude_agent_sdk import RateLimitEvent, RateLimitInfo, RateLimitStatus, RateLimitType
from conftest import consuming, make_stream_harness, result_msg
from pydantic import SecretStr
from wait_util import wait_for_condition

import core.config as cfg
from core.client import _note_rate_limit
from core.model_access import clear_model_access, model_access_available
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
    sub = state.event_bus.subscribe()

    await clear_model_access(state=state, config=config)

    assert state.persisted.provider_cooldown is None
    assert model_access_available(state)
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


# --- the gate: what actually pauses model work while a cooldown is open ---


@pytest.mark.anyio
async def test_wait_for_model_access_returns_immediately_when_available(config, state):
    from core.model_access import wait_for_model_access

    assert await wait_for_model_access(state=state, config=config) is True


@pytest.mark.anyio
async def test_wait_for_model_access_clears_an_expired_cooldown_and_proceeds(config, state):
    """An elapsed cooldown is dropped on the next gate rather than waiting on a stale deadline."""
    from core.model_access import wait_for_model_access

    state.persisted.provider_cooldown = ProviderCooldown(until=1, window="five_hour")
    sub = state.event_bus.subscribe()

    assert await wait_for_model_access(state=state, config=config) is True

    assert state.persisted.provider_cooldown is None
    event = sub.get_nowait()
    assert event["type"] == "model_access"
    assert event["state"] == "available"


@pytest.mark.anyio
async def test_wait_for_model_access_blocks_until_the_cooldown_expires(config, state):
    """The whole point of the feature: an open cooldown parks the caller instead of querying."""
    from core.model_access import wait_for_model_access

    state.persisted.provider_cooldown = ProviderCooldown(until=int(time.time()) + 60, window="five_hour")

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(wait_for_model_access(state=state, config=config), timeout=0.1)

    assert state.persisted.provider_cooldown is not None  # still cooling down, nothing cleared


@pytest.mark.anyio
async def test_wait_for_model_access_returns_false_only_on_shutdown(config, state):
    """converse turns this False into a CancelledError, which _run_one_turn re-raises only because
    shutdown is set. If this ever returned False for another reason, that would become a restart."""
    from core.model_access import wait_for_model_access

    state.persisted.provider_cooldown = ProviderCooldown(until=int(time.time()) + 60, window="five_hour")
    state.shutdown_event.set()

    assert await wait_for_model_access(state=state, config=config) is False
    assert state.persisted.provider_cooldown is not None  # a shutdown must not clear a live cooldown


@pytest.mark.anyio
async def test_model_access_available_tracks_the_cooldown(config, state):
    from core.model_access import model_access_available

    assert model_access_available(state) is True
    state.persisted.provider_cooldown = ProviderCooldown(until=int(time.time()) + 60, window="five_hour")
    assert model_access_available(state) is False
    state.persisted.provider_cooldown = ProviderCooldown(until=1, window="five_hour")
    assert model_access_available(state) is True  # expired reads as available


@pytest.mark.anyio
async def test_shutdown_during_a_cooldown_hands_the_turn_back(config, state):
    """Shutdown is the only thing that ends the cooldown wait, and it must not consume the turn it
    was holding. Only shutdown_event is set here, so the gate's own branch runs rather than the
    loop's top-of-iteration shutdown check."""
    import core.models as vm
    from core.loops import _run_messages_with_preempts

    queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()
    boot_turn = vm.QueuedTurn("migration", False, [], interruptible=False)
    state.persisted.provider_cooldown = ProviderCooldown(until=int(time.time()) + 3600, window="five_hour")
    state.shutdown_event.set()  # graceful_shutdown deliberately left unset

    await _run_messages_with_preempts(boot_turn, queue=queue, state=state, config=config)

    assert [queue.get_nowait().text for _ in range(queue.qsize())] == ["migration"]


@pytest.mark.anyio
async def test_requeue_returns_every_unstarted_turn(config, state):
    """A boot turn carries no notification file, so one dropped on shutdown is lost outright."""
    import core.models as vm
    from core.loops import _requeue

    queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()
    items = [vm.QueuedTurn(text, False, [], interruptible=False) for text in ("migration", "sync", "greeting")]

    await _requeue(items, queue)

    assert [queue.get_nowait().text for _ in range(queue.qsize())] == ["migration", "sync", "greeting"]


# --- each provider answers for its own 429 ---


def _rejected(details: str):
    """A ResultMessage carrying a provider's 429 and its error text."""
    from unittest.mock import MagicMock

    from claude_agent_sdk import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.api_error_status = 429
    return msg, (details,)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "details", "window", "min_seconds"),
    [
        ("zai", '{"error":{"code":"1302","message":"Rate limit reached for requests"}}', "requests", 30),
        ("zai", "Usage limit reached for the past 5 hours. Insufficient balance", "5 hours", 4 * 3600),
        ("zai", "Usage limit reached for the past 7 days. Insufficient balance", "7 days", 6 * 24 * 3600),
        ("kimi", "Organization-level RPM limit reached", "requests per minute", 30),
        ("kimi", "Organization-level TPD limit reached", "tokens per day", 12 * 3600),
        ("kimi", "The engine is currently overloaded, please try again later", "overloaded", 30),
    ],
)
async def test_a_provider_names_its_own_window(config, state, kind, details, window, min_seconds):
    """The vendors publish what each 429 means; reading it beats a single guessed duration."""
    from core.client import _note_rejected_turn

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind=kind, model="m")
    msg, detail_texts = _rejected(details)

    await _note_rejected_turn(msg, state=state, config=config, details=detail_texts)

    cooldown = state.persisted.provider_cooldown
    assert cooldown is not None
    assert cooldown.window == window
    assert cooldown.until >= time.time() + min_seconds


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kind", "details"),
    [
        ("zai", '{"error":{"code":"1309","message":"Your GLM Coding Plan package has expired"}}'),
        ("zai", '{"error":{"code":"1311","message":"subscription plan does not yet include access"}}'),
        ("kimi", "exceeded_current_quota_error: Account balance is insufficient"),
    ],
)
async def test_a_429_that_waiting_cannot_fix_is_terminal_not_a_cooldown(config, state, kind, details):
    """Z.AI and Kimi return 429 where every other provider returns 402. It has to reach the same
    terminal path, so the app asks the user to act instead of hiding it behind silent retries."""
    from core.client import _note_rejected_turn
    from core.provider import is_terminal_provider_error

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind=kind, model="m")
    msg, detail_texts = _rejected(details)

    await _note_rejected_turn(msg, state=state, config=config, details=detail_texts)

    assert state.persisted.provider_cooldown is None, "waiting cannot fix this, so no cooldown"
    assert is_terminal_provider_error(kind, assistant_error=None, api_error_status=429, details=detail_texts)


@pytest.mark.anyio
async def test_a_provider_that_does_not_answer_is_a_logged_gap_not_a_guess(config, state):
    """No blanket fallback: a provider with no published meaning for its 429 gets no invented one."""
    from core.client import _note_rejected_turn
    from core.provider import is_terminal_provider_error

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="openai", model="gpt")
    msg, detail_texts = _rejected("429 Too Many Requests")

    await _note_rejected_turn(msg, state=state, config=config, details=detail_texts)

    assert state.persisted.provider_cooldown is None
    # An unknown 429 is a gap, not a terminal credential failure: it must not sign the agent out.
    assert not is_terminal_provider_error("openai", assistant_error=None, api_error_status=429, details=detail_texts)


@pytest.mark.anyio
async def test_a_named_window_never_shortens_a_precise_one(config, state):
    """Claude's structured window and a provider 429 can both land for one rejection, in either
    order, so the shorter must not win."""
    from core.client import _note_rejected_turn

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="zai", model="glm-5")
    precise = int(time.time()) + 5 * 3600
    state.persisted.provider_cooldown = ProviderCooldown(until=precise, window="5 hours")
    msg, detail_texts = _rejected("Rate limit reached for requests")

    await _note_rejected_turn(msg, state=state, config=config, details=detail_texts)

    assert state.persisted.provider_cooldown is not None
    assert state.persisted.provider_cooldown.until == precise


def _drain(sub):
    return [sub.get_nowait() for _ in range(sub.qsize())]
