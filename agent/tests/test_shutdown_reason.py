"""Tests for vestad's one-shot shutdown-reason handoff."""

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.config as cfg
import core.models as vm
from core import state_store
from core.main import (
    _consume_restart_reason,
    _log_startup_reason,
    _make_signal_handler,
    run_vesta,
)


def _config(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_sigterm_hands_reason_to_usual_shutdown_log_without_extra_line(tmp_path):
    config = _config(tmp_path)
    state = vm.State()
    state_store.pending_shutdown_reason_path(config).write_text(
        "backup: you were paused for a scheduled backup"
    )

    with patch("core.main.logger.shutdown") as shutdown_log:
        _make_signal_handler(state, config)(signal.SIGTERM, None)

    assert state.shutdown_reason == "backup: you were paused for a scheduled backup"
    assert state.graceful_shutdown.is_set()
    shutdown_log.assert_not_called()
    assert not state_store.pending_shutdown_reason_path(config).exists()


@pytest.mark.anyio
async def test_usual_shutdown_log_includes_handed_reason(tmp_path):
    config = _config(tmp_path)
    for path in [config.notifications_dir, config.logs_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)
    state = vm.State(shutdown_reason="backup: you were paused for a scheduled backup")
    state.graceful_shutdown.set()

    async def parked_worker(*_args, **_kwargs):
        await asyncio.Event().wait()

    with (
        patch("core.main.start_ws_server", new_callable=AsyncMock) as start_ws,
        patch("core.main.message_processor", side_effect=parked_worker),
        patch("core.main.monitor_loop", side_effect=parked_worker),
        patch("core.main.collect_boot_turns", return_value=[]),
        patch("core.main.logger.shutdown") as shutdown_log,
    ):
        runner = MagicMock()
        runner.cleanup = AsyncMock()
        start_ws.return_value = runner

        crashed = await run_vesta(config, state=state)

    assert crashed is False
    assert any(
        call.args == ("Shutting down (backup: you were paused for a scheduled backup)",)
        for call in shutdown_log.call_args_list
    )


def test_boot_discards_stale_shutdown_reason_without_using_it_as_restart_reason(tmp_path):
    config = _config(tmp_path)
    state = vm.State()
    state_store.pending_shutdown_reason_path(config).write_text(
        "backup: stale reason captured in a snapshot"
    )

    reason = _consume_restart_reason(state, config, first_start=False)

    assert reason == vm.CRASH_RESTART
    assert not state_store.pending_shutdown_reason_path(config).exists()


def test_restart_reason_always_gets_a_dedicated_startup_line():
    with patch("core.main.logger.startup") as startup_log:
        _log_startup_reason(
            "backup: you were paused for a scheduled backup",
            first_start=False,
        )

    startup_log.assert_called_once_with(
        "Restart reason: backup: you were paused for a scheduled backup"
    )


def test_first_start_uses_startup_reason_label():
    with patch("core.main.logger.startup") as startup_log:
        _log_startup_reason(vm.FIRST_START_REASON, first_start=True)

    startup_log.assert_called_once_with("Startup reason: first start")
