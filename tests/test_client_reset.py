"""Test client reset functionality.

Verifies that resetting the Claude client after dreamer operations
doesn't create a zombie state and keeps the client responsive.
"""

import asyncio

from pydantic import SecretStr

import vesta.models as vm
import vesta.main as vmain
from vesta.core.client import reset_client_context, process_message
from vesta.core.dreamer import preserve_memory


def _prepare_state_dir(state_dir):
    """Create required test directories."""
    for folder in ("memory", "logs", "data", "notifications"):
        (state_dir / folder).mkdir(parents=True, exist_ok=True)


def _run(coro):
    """Run async test scenario."""
    return asyncio.run(coro)


async def _run_test_scenario(state_dir, test_fn):
    """Run a test scenario within Vesta lifecycle."""
    config = vm.VestaConfig(
        state_dir=state_dir,
        microsoft_mcp_client_id=SecretStr("test"),
        ephemeral=True,
        mcps=[],
    )

    state = await vmain.init_state(config=config)

    try:
        await test_fn(state, config)
    finally:
        if state.client:
            try:
                await state.client.__aexit__(None, None, None)
            except Exception:
                pass


def test_client_reset_maintains_responsiveness(tmp_path):
    """Client should remain responsive after reset (simulating post-dreamer)."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        # Verify initial client exists
        assert state.client is not None, "Initial client should exist"

        # Reset the client (this is what happens after dreamer)
        await reset_client_context(state, config=config)
        assert state.client is not None, "Client should exist after reset"

        # Verify client is still responsive
        responses, _ = await asyncio.wait_for(
            process_message("Say 'hello' if you can hear me", state=state, config=config, is_user=True), timeout=30.0
        )
        assert responses, "Client should respond after reset"

    _run(_run_test_scenario(state_dir, test_fn))


def test_client_shutdown_after_reset(tmp_path):
    """Client should shutdown cleanly even after reset."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        # Reset client
        await reset_client_context(state, config=config)

        # Shutdown should not crash
        if state.client:
            await state.client.__aexit__(None, None, None)

    _run(_run_test_scenario(state_dir, test_fn))


def test_full_nightly_flow_preserve_memory_then_reset(tmp_path):
    """Full nightly flow: preserve_memory → reset_client_context should keep client responsive."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        # Add some conversation history for dreamer to process
        async with state.conversation_history_lock:
            state.conversation_history.extend(
                [
                    {"role": "user", "content": "What's the weather like?"},
                    {"role": "assistant", "content": "I don't have access to current weather data."},
                    {"role": "user", "content": "Can you remember my favorite color is blue?"},
                    {"role": "assistant", "content": "I'll remember that your favorite color is blue."},
                ]
            )

        # Run preserve_memory (this is what happens at night)
        updated = await preserve_memory(state, config=config)

        # If memory was updated, reset client (matching nightly flow)
        if updated:
            await reset_client_context(state, config=config)
            assert state.client is not None, "Client should exist after reset"

            # Verify client is still responsive after full nightly flow
            responses, _ = await asyncio.wait_for(
                process_message("Are you still there?", state=state, config=config, is_user=True), timeout=30.0
            )
            assert responses, "Client should respond after preserve_memory + reset"

    _run(_run_test_scenario(state_dir, test_fn))
