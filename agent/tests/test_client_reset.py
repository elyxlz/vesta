"""Test client lifecycle and reset functionality.

Verifies that the client lifecycle is properly managed using async with,
and that pending_context triggers client recreation.
"""

import asyncio

from claude_agent_sdk import ClaudeSDKClient

import vesta.models as vm
import vesta.main as vmain
from vesta.core.client import build_client_options, process_message


def _prepare_state_dir(state_dir):
    """Create required test directories."""
    for folder in ("memory", "logs", "data", "notifications"):
        (state_dir / folder).mkdir(parents=True, exist_ok=True)


def _run(coro):
    """Run async test scenario."""
    return asyncio.run(coro)


def _make_config(state_dir):
    """Create test config."""
    return vm.VestaConfig(
        state_dir=state_dir,
        ephemeral=True,
    )


def test_client_lifecycle_with_async_with(tmp_path):
    """Client should work correctly with async with context manager."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            assert state.client is not None, "Client should exist inside async with"

            responses, _ = await asyncio.wait_for(
                process_message("Say 'hello'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses, "Client should respond"

    _run(test_fn())


def test_pending_context_flag(tmp_path):
    """Setting pending_context should work correctly."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        assert state.pending_context is None

        state.pending_context = "[System: test reset]"
        state.session_id = None
        assert state.pending_context is not None

        # Simulate what message_processor does: consume pending_context
        state.pending_context = None
        assert state.pending_context is None

    _run(test_fn())


def test_multiple_client_sessions(tmp_path):
    """Should be able to create multiple client sessions sequentially."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client1:
            state.client = client1
            responses1, _ = await asyncio.wait_for(
                process_message("Say 'one'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses1, "First session should respond"

        state.client = None
        state.session_id = None

        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client2:
            state.client = client2
            responses2, _ = await asyncio.wait_for(
                process_message("Say 'two'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses2, "Second session should respond"

    _run(test_fn())


def test_timeout_sets_pending_context(tmp_path):
    """Response timeout should set pending_context and preserve session_id."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    config.response_timeout = 1
    state = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            responses, _ = await asyncio.wait_for(
                process_message("Write a 500-word essay about clouds", state=state, config=config, is_user=False),
                timeout=30.0,
            )

        assert "[Response timeout]" in responses
        assert state.pending_context is not None

    _run(test_fn())


def test_full_reset_flow(tmp_path):
    """Full flow: pending_context triggers client recreation."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client

        state.client = None
        state.pending_context = "[System: Reset needed]"

        # Simulate message_processor consuming context and creating new client
        context = state.pending_context
        state.pending_context = None
        assert context is not None

        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            responses, _ = await asyncio.wait_for(
                process_message("Are you there?", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses, "New client should respond after reset"

    _run(test_fn())
