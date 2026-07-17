"""Raw BiDi client: id correlation, error propagation, event fan-out.

Driven via asyncio.run rather than pytest-asyncio to avoid a new test dependency.
"""

from __future__ import annotations

import asyncio

import pytest
from vesta_browser import bidi as bidi_module
from vesta_browser.bidi import BidiClient, BidiError

from .fake_bidi import FakeBidiServer


async def _with_client(body, snapshot_nodes=None, withhold=None):
    server = FakeBidiServer(snapshot_nodes, withhold=withhold)
    url = await server.start()
    client = BidiClient()
    await client.connect(url)
    try:
        return await body(server, client)
    finally:
        await client.close()
        await server.stop()


def test_new_session_returns_context():
    async def body(_server, client):
        return await client.new_session()

    assert asyncio.run(_with_client(body)) == "ctx-1"


def test_send_correlates_by_id():
    async def body(_server, client):
        await client.new_session()
        return await asyncio.gather(
            client.send("browsingContext.navigate", {"context": "ctx-1", "url": "https://a.test"}),
            client.send("browsingContext.navigate", {"context": "ctx-1", "url": "https://b.test"}),
        )

    results = asyncio.run(_with_client(body))
    assert {r["url"] for r in results} == {"https://a.test", "https://b.test"}


def test_error_response_raises():
    async def body(_server, client):
        return await client.send("nonexistent.method", {})

    with pytest.raises(BidiError) as excinfo:
        asyncio.run(_with_client(body))
    assert excinfo.value.code == "unknown command"


def test_event_lands_on_queue():
    async def body(_server, client):
        await client.new_session()
        load_events = client.on_event("browsingContext.load")
        await client.send("browsingContext.navigate", {"context": "ctx-1", "url": "https://a.test"})
        return await asyncio.wait_for(load_events.get(), timeout=2)

    event = asyncio.run(_with_client(body))
    assert event["url"] == "https://a.test"


CREATE = "browsingContext.create"
TEST_TIMEOUT_S = 0.2
HANG_GUARD_S = 5


async def _create_tab(client):
    return await asyncio.wait_for(client.send(CREATE, {"type": "tab"}), timeout=HANG_GUARD_S)


def test_withheld_response_raises_timeout_naming_the_method(monkeypatch):
    """A browser that accepts a command and never answers must error, not hang forever."""
    monkeypatch.setattr(bidi_module, "BIDI_RESPONSE_TIMEOUT_S", TEST_TIMEOUT_S)

    async def body(_server, client):
        await client.new_session()
        return await _create_tab(client)

    with pytest.raises(BidiError) as excinfo:
        asyncio.run(_with_client(body, withhold={CREATE}))
    assert excinfo.value.code == "timeout"
    assert CREATE in excinfo.value.message


def test_timed_out_request_is_dropped_from_pending(monkeypatch):
    """The abandoned future is released, so a wedged browser cannot accumulate them."""
    monkeypatch.setattr(bidi_module, "BIDI_RESPONSE_TIMEOUT_S", TEST_TIMEOUT_S)

    async def body(_server, client):
        await client.new_session()
        with pytest.raises(BidiError):
            await _create_tab(client)
        return dict(client._pending)

    assert asyncio.run(_with_client(body, withhold={CREATE})) == {}


def test_a_withheld_response_does_not_block_later_commands(monkeypatch):
    """Each request is bounded on its own; one silent command must not wedge the client."""
    monkeypatch.setattr(bidi_module, "BIDI_RESPONSE_TIMEOUT_S", TEST_TIMEOUT_S)

    async def body(_server, client):
        await client.new_session()
        with pytest.raises(BidiError):
            await _create_tab(client)
        return await client.send("browsingContext.navigate", {"context": "ctx-1", "url": "https://a.test"})

    assert asyncio.run(_with_client(body, withhold={CREATE}))["url"] == "https://a.test"
