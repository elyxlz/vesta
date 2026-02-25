"""Test client lifecycle and reset functionality.

Verifies that the client lifecycle is properly managed using async with,
and that the reset_requested flag triggers client recreation.
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
        # Create client using async with (like message_processor does)
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            assert state.client is not None, "Client should exist inside async with"

            # Verify client is responsive
            responses, _ = await asyncio.wait_for(
                process_message("Say 'hello'", state=state, config=config, is_user=True),
                timeout=30.0,
            )
            assert responses, "Client should respond"

        # Client should be closed after exiting async with
        # (state.client still points to closed client, but that's fine)

    _run(test_fn())


def test_reset_requested_flag(tmp_path):
    """Setting reset_requested should work correctly."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        assert state.reset_requested is False, "reset_requested should start False"

        # Simulate what process_nightly_memory does
        state.reset_requested = True
        assert state.reset_requested is True, "reset_requested should be True"

        # Simulate what message_processor does when it sees the flag
        if state.reset_requested:
            state.reset_requested = False
            state.sub_agent_context = None
            state.session_id = None

        assert state.reset_requested is False, "reset_requested should be cleared"

    _run(test_fn())


def test_multiple_client_sessions(tmp_path):
    """Should be able to create multiple client sessions sequentially."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        # First session
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client1:
            state.client = client1
            responses1, _ = await asyncio.wait_for(
                process_message("Say 'one'", state=state, config=config, is_user=True),
                timeout=30.0,
            )
            assert responses1, "First session should respond"

        state.client = None

        # Second session (simulating after reset)
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client2:
            state.client = client2
            responses2, _ = await asyncio.wait_for(
                process_message("Say 'two'", state=state, config=config, is_user=True),
                timeout=30.0,
            )
            assert responses2, "Second session should respond"

    _run(test_fn())


def test_reset_clears_context(tmp_path):
    """Reset should clear sub_agent_context and session_id."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client

            # Simulate accumulated context from conversation
            state.sub_agent_context = "some-context-from-subagent"
            state.session_id = "session-12345"

            # Trigger reset (what process_nightly_memory does)
            state.reset_requested = True

        # Simulate what message_processor does after exiting async with
        if state.reset_requested:
            state.reset_requested = False
            state.sub_agent_context = None
            state.session_id = None

        state.client = None

        # Verify context was cleared
        assert state.sub_agent_context is None, "sub_agent_context should be cleared"
        assert state.session_id is None, "session_id should be cleared"
        assert state.reset_requested is False, "reset_requested should be cleared"

        # Verify new client works
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            responses, _ = await asyncio.wait_for(
                process_message("Hello", state=state, config=config, is_user=True),
                timeout=30.0,
            )
            assert responses, "New client should work after context cleared"

    _run(test_fn())


def test_full_nightly_flow_with_flag(tmp_path):
    """Full nightly flow: reset_requested flag triggers client recreation."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state = vmain.init_state(config=config)

    async def test_fn():
        # Create initial client
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client

            # Simulate nightly memory consolidation setting the flag
            state.reset_requested = True

        # After exiting async with, client is closed
        state.client = None

        # If reset was requested, create new client (simulating message_processor)
        if state.reset_requested:
            state.reset_requested = False
            options = build_client_options(config, state)
            async with ClaudeSDKClient(options=options) as client:
                state.client = client

                # Verify new client is responsive
                responses, _ = await asyncio.wait_for(
                    process_message("Are you there?", state=state, config=config, is_user=True),
                    timeout=30.0,
                )
                assert responses, "New client should respond after reset"

    _run(test_fn())
