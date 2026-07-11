"""Raw BiDi client: id correlation, error propagation, event fan-out.

Driven via asyncio.run rather than pytest-asyncio to avoid a new test dependency.
"""

from __future__ import annotations

import asyncio

import pytest

from vesta_browser.bidi import BidiClient, BidiError

from .fake_bidi import FakeBidiServer


async def _with_client(body, snapshot_nodes=None):
    server = FakeBidiServer(snapshot_nodes)
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
