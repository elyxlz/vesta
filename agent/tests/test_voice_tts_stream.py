"""The id-store backing the native-audio TTS stream route (issue #466)."""

from voice import tts_pending


def test_register_then_resolve_returns_the_text():
    store: tts_pending.PendingStore = {}
    token = tts_pending.register(store, "hello there", now=100.0)
    assert tts_pending.resolve(store, token, now=100.0) == "hello there"


def test_distinct_registrations_get_distinct_ids():
    store: tts_pending.PendingStore = {}
    first = tts_pending.register(store, "one", now=0.0)
    second = tts_pending.register(store, "two", now=0.0)
    assert first != second
    assert tts_pending.resolve(store, first, now=0.0) == "one"
    assert tts_pending.resolve(store, second, now=0.0) == "two"


def test_unknown_id_resolves_to_none():
    store: tts_pending.PendingStore = {}
    assert tts_pending.resolve(store, "nope", now=0.0) is None


def test_id_resolves_repeatedly_within_its_ttl():
    store: tts_pending.PendingStore = {}
    token = tts_pending.register(store, "replayable", now=0.0, ttl=10.0)
    assert tts_pending.resolve(store, token, now=5.0) == "replayable"
    assert tts_pending.resolve(store, token, now=9.0) == "replayable"


def test_expired_id_resolves_to_none():
    store: tts_pending.PendingStore = {}
    token = tts_pending.register(store, "stale", now=0.0, ttl=10.0)
    assert tts_pending.resolve(store, token, now=10.0) is None


def test_resolving_prunes_other_expired_entries():
    store: tts_pending.PendingStore = {}
    stale = tts_pending.register(store, "stale", now=0.0, ttl=10.0)
    fresh = tts_pending.register(store, "fresh", now=0.0, ttl=100.0)
    assert tts_pending.resolve(store, fresh, now=20.0) == "fresh"
    assert stale not in store
