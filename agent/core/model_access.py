"""Provider-independent ownership of temporary model-access cooldowns."""

import asyncio
import time

from . import config as cfg
from . import models as vm
from . import state_store
from .events import ModelAccessEvent, model_access_info
from .provider import ProviderCooldown, active_cooldown, rate_limit_cooldown


def model_access_available(state: vm.State, *, now: float | None = None) -> bool:
    return active_cooldown(state.persisted.provider_cooldown, now=now) is None


def model_access_event(state: vm.State) -> ModelAccessEvent:
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    return {"type": "model_access", **model_access_info(cooldown)}


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
    state.persisted.provider_cooldown = cooldown
    state.current_turn_rate_limited = True
    await state_store.save_state_async(state.persisted, config)
    state.event_bus.emit(model_access_event(state))
    return cooldown


async def wait_for_model_access(*, state: vm.State, config: cfg.VestaConfig) -> bool:
    cooldown = active_cooldown(state.persisted.provider_cooldown)
    if cooldown is None:
        if state.persisted.provider_cooldown is not None:
            state.persisted.provider_cooldown = None
            await state_store.save_state_async(state.persisted, config)
            state.event_bus.emit(model_access_event(state))
        return True
    timeout = max(cooldown.until - time.time(), 0)
    try:
        await asyncio.wait_for(state.shutdown_event.wait(), timeout=timeout)
        return False
    except TimeoutError:
        state.persisted.provider_cooldown = None
        await state_store.save_state_async(state.persisted, config)
        state.event_bus.emit(model_access_event(state))
        return True
