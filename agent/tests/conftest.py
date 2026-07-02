import asyncio
import os

import pytest
import core.models as vm
from core.events import EventBus

os.environ.pop("CLAUDECODE", None)
os.environ.setdefault("WS_PORT", "17865")


@pytest.fixture
def config(tmp_path, monkeypatch):
    # Drive agent_dir through AGENT_DIR so the config field and config_store_path() agree (both
    # resolve from the env), keeping the writable settings store inside the test's tmp dir rather
    # than the real ~/agent. model/provider/personality fall back to the shipped defaults.json.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    return vm.VestaConfig()


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


@pytest.fixture(autouse=True)
def _no_early_result_suspicion(monkeypatch):
    # Mocked turns complete in milliseconds, which converse would treat as a suspiciously early
    # result (production turns need an API round trip) and pay the confirmation wait on every
    # test. Disable the suspicion window by default; tests exercising it patch it back on.
    import core.client

    monkeypatch.setattr(core.client, "_EARLY_RESULT_SUSPECT_S", 0.0)
