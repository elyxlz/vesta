"""Provider-independent ownership of temporary model-access cooldowns."""

import asyncio
import time

from . import config as cfg
from . import models as vm
from . import state_store
from .events import ModelAccessEvent, ModelAccessInfo
from .provider import ProviderCooldown, active_cooldown, rate_limit_cooldown


def model_access_available(state: vm.State, *, now: float | None = None) -> bool:
    return active_cooldown(state.persisted.provider_cooldown, now=now) is None


def model_access_snapshot(state: vm.State) -> ModelAccessInfo:
    """The wire shape clients read. Lives here rather than in events so the event bus stays
    ignorant of the provider domain."""
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    if cooldown is None:
        return {"state": "available", "reason": None, "until": None, "window": None}
    return {"state": "cooling_down", "reason": cooldown.reason, "until": cooldown.until, "window": cooldown.window}


def model_access_event(state: vm.State) -> ModelAccessEvent:
    return {"type": "model_access", **model_access_snapshot(state)}


async def _set_cooldown(cooldown: ProviderCooldown | None, *, state: vm.State, config: cfg.VestaConfig) -> None:
    """The one way this state changes: persist the transition, then publish it."""
    state.persisted.provider_cooldown = cooldown
    await state_store.save_state_async(state.persisted, config)
    state.event_bus.emit(model_access_event(state))


async def activate_rate_limit(
    *,
    state: vm.State,
    config: cfg.VestaConfig,
    resets_at: int | None,
    window: str | None,
) -> ProviderCooldown:
    """Persist and publish one provider's rejected model request.

    Provider adapters own parsing their native signal; this function owns the
    shared state transition so every provider blocks scheduling identically.
    """
    cooldown = rate_limit_cooldown(resets_at=resets_at, window=window)
    await _set_cooldown(cooldown, state=state, config=config)
    return cooldown


def note_rate_limit_once(*, state: vm.State, window: str | None, resets_at: int | None, notice: str) -> bool:
    """Emit the rate-limit notice for a window the agent has not already announced. Returns whether
    it was new, so a caller can decide whether to raise a user-facing notification too."""
    window_key = (window, resets_at)
    if window_key == state.rate_limit_noticed:
        return False
    state.rate_limit_noticed = window_key
    state.event_bus.emit({"type": "rate_limited", "text": notice, "window": window, "resets_at": resets_at})
    return True


async def clear_model_access(*, state: vm.State, config: cfg.VestaConfig) -> None:
    """Clear a cooldown when credentials or providers change.

    Cooldowns intentionally survive ordinary restarts, but must not follow a user onto a newly
    selected provider or credential.
    """
    if state.persisted.provider_cooldown is None:
        return
    await _set_cooldown(None, state=state, config=config)


async def wait_for_model_access(*, state: vm.State, config: cfg.VestaConfig) -> bool:
    """Park until model access returns, then drop the spent cooldown. Returns False only when
    shutdown ended the wait, which is what callers read as "do not start this turn"."""
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    if cooldown is not None:
        try:
            await asyncio.wait_for(state.shutdown_event.wait(), timeout=max(cooldown.until - time.time(), 0))
            return False
        except TimeoutError:
            pass
    # Reached whether the cooldown had already lapsed or just ran out.
    if state.persisted.provider_cooldown is not None:
        await _set_cooldown(None, state=state, config=config)
    return True
