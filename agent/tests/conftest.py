import asyncio
import os

import pytest
import core.models as vm
from core.events import EventBus

os.environ.pop("CLAUDECODE", None)
os.environ.setdefault("WS_PORT", "17865")
# vestad always writes AGENT_PERSONALITY into the agent's env; mirror that for the suite
# so VestaConfig (which now requires it) constructs without each test having to set it.
os.environ.setdefault("AGENT_PERSONALITY", "dry")


@pytest.fixture
def config(tmp_path):
    return vm.VestaConfig(agent_dir=tmp_path / "agent")


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
