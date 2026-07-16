import asyncio
import contextlib
import os
import time
import typing as tp
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.config as cfg
import core.models as vm
from core.events import EventBus, StreamEvent

os.environ.pop("CLAUDECODE", None)
os.environ.setdefault("WS_PORT", "17865")


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Drive agent_dir through AGENT_DIR so the config field and config_store_path() agree (both
    # resolve from the env), keeping the writable settings store inside the test's tmp dir rather
    # than the real ~/agent. model/provider/personality fall back to the shipped defaults.json.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    return cfg.VestaConfig()


@pytest.fixture
def event_bus(tmp_path):
    bus = EventBus(data_dir=tmp_path)
    yield bus
    bus.close()


@pytest.fixture
def state():
    s = vm.State()
    s.shutdown_event = asyncio.Event()
    return s


def idle_message_stream():
    """receive_messages() stand-in that never yields: parks the stream consumer.

    message_processor spawns consume_stream against its client; mock clients hand it this
    so the consumer idles instead of erroring on a non-iterable MagicMock."""

    async def _stream():
        await asyncio.Event().wait()
        yield  # never reached; makes this an async generator

    return _stream()


def assistant_msg(content):
    from claude_agent_sdk import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = content
    return msg


def result_msg():
    from claude_agent_sdk import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.content = []
    msg.usage = None
    msg.total_cost_usd = None
    msg.duration_ms = 0
    msg.session_id = None  # no persist: harness configs point at the real home, not a tmp dir
    return msg


def make_stream_harness(response_timeout: int | None = None):
    """Build a stream-consumer test harness: state/config and a mock SDK client whose
    receive_messages() yields from `message_queue`.

    Returns (state, config, mock_client, emitted, message_queue, consumed). Run the real
    consume_stream task (via `consuming`) for converse/compact_session to make progress;
    `consumed` records each message right after the consumer finished dispatching it,
    giving tests a handshake signal instead of guessing with sleeps.
    """
    from core.provider import ProviderAuthState, ProviderStatus

    emitted: list[tuple[str, float]] = []
    if response_timeout is None:
        config = cfg.VestaConfig(interrupt_timeout=0.5)
    else:
        config = cfg.VestaConfig(interrupt_timeout=0.5, response_timeout=response_timeout)
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    class _TrackingEventBus(EventBus):
        """EventBus that records each emitted assistant text with its wall-clock instant."""

        def emit(self, event: StreamEvent) -> None:
            if event["type"] == "assistant" and "text" in event:
                emitted.append((str(event["text"]), time.monotonic()))
            super().emit(event)

    state.event_bus = _TrackingEventBus()

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    message_queue: asyncio.Queue[tp.Any] = asyncio.Queue()
    consumed: list[tp.Any] = []

    async def _receive_messages():
        while True:
            msg = await message_queue.get()
            yield msg
            # The generator only resumes here once the consumer's async-for advanced past
            # `msg` — i.e. its dispatch (emit/turn bookkeeping) has fully completed.
            consumed.append(msg)

    mock_client.receive_messages = MagicMock(side_effect=_receive_messages)

    return state, config, mock_client, emitted, message_queue, consumed


@contextlib.asynccontextmanager
async def consuming(state, config):
    """Run the real consume_stream task for the duration of the block (cancelled on exit)."""
    from core.client import consume_stream

    task = asyncio.create_task(consume_stream(state=state, config=config))
    try:
        yield task
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
