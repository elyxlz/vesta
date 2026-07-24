"""Event-union fixture emitter: serialize the tap-read subset of StreamEvent variants plus a
SnapshotEvent through the real EventBus emit/read path into a committed JSON fixture, so the vestad
aggregator test can parse the exact Python-to-Rust wire shape. Regenerate with REGEN_EVENT_FIXTURES=1.

The fixture's contract is the core-`/ws` -> vestad-tap seam (D11): the tap reads only `status`,
`model_access`, `notification`, and `notification_cleared`. Core's internal StreamEvent union keeps other variants
(assistant/thinking/error/rate_limited/...) for history, but they are not part of the tap contract, so
they are not in the fixture.
"""

import json
import os
from pathlib import Path

from core.events import (
    EventBus,
    ModelAccessEvent,
    ModelAccessInfo,
    NotificationClearedEvent,
    NotificationEvent,
    SnapshotEvent,
    StatusEvent,
    StreamEvent,
)

# ts is a wall-clock value stamped inside emit; normalize it so the committed fixture is stable. The
# ids are the contract under test and are kept exactly as the real emit/read path produced them.
_FIXED_TS = "2026-01-01T00:00:00+00:00"

# The exact set of event types the vestad tap reads off core's /ws. status and notification_cleared are
# live-only (negative session ids); notification is persisted (a positive rowid).
_TAP_READ_TYPES: frozenset[str] = frozenset({"status", "model_access", "notification", "notification_cleared"})


def _variants() -> list[StreamEvent]:
    """One representative instance of each tap-read StreamEvent variant."""
    return [
        StatusEvent(type="status", state="thinking"),
        ModelAccessEvent(
            type="model_access",
            state="cooling_down",
            reason="rate_limit",
            until=2_000_000_000,
            window="five_hour",
        ),
        NotificationEvent(
            type="notification",
            source="whatsapp",
            summary="new message",
            notif_type="message",
            sender="Alex",
            fields={"chat_name": "Bride squad"},
            decided="interrupt",
            notif_id="whatsapp-123",
        ),
        NotificationClearedEvent(type="notification_cleared", notif_id="whatsapp-123"),
    ]


def _emit_all(bus: EventBus, variants: list[StreamEvent]) -> list[StreamEvent]:
    """Emit each variant so id is stamped the way the real wire does it: the persisted `notification`
    through bus.emit (a positive rowid), status/notification_cleared through bus.emit (the negative live
    counter). Normalize ts for a stable fixture."""
    emitted: list[StreamEvent] = []
    for event in variants:
        bus.emit(event)
        event["ts"] = _FIXED_TS
        emitted.append(event)
    return emitted


def _snapshot() -> SnapshotEvent:
    """Build the connect snapshot the way api.py does. The tap reads `state`, `config.timezone`, and
    `notifications.pending`; chat is not on the snapshot (the app-chat skill owns it). The snapshot is a
    frame, not an event, so it has no id of its own."""
    return SnapshotEvent(
        type="snapshot",
        state="idle",
        notifications={"pending": ["whatsapp-123"]},
        config={"timezone": "America/New_York"},
        model_access=ModelAccessInfo(state="available", reason=None, until=None, window=None),
    )


def _fixture_content(tmp_path: Path) -> str:
    bus = EventBus(data_dir=tmp_path)
    try:
        events = _emit_all(bus, _variants())
        snapshot = _snapshot()
    finally:
        bus.close()
    payload = {"events": events, "snapshot": snapshot}
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _fixture_path() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "event-union.json"


def test_event_union_fixture_up_to_date(tmp_path):
    """Emit every tap-read variant plus a snapshot through the real path and fail if the committed
    fixture is stale. Regenerate with REGEN_EVENT_FIXTURES=1."""
    path = _fixture_path()
    content = _fixture_content(tmp_path)
    if "REGEN_EVENT_FIXTURES" in os.environ:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return
    committed = path.read_text() if path.exists() else ""
    assert committed == content, (
        "\n\nEvent-union fixture is stale.\nRegenerate with:\n"
        "  cd agent && REGEN_EVENT_FIXTURES=1 uv run pytest tests/test_event_union_fixture.py\n"
        f"then commit {path}\n"
    )


def test_every_variant_carries_a_stable_id(tmp_path):
    """Every tap-read variant carries an id with the sign the seam relies on: status and
    notification_cleared are live-only (negative session ids); notification is persisted (a positive
    rowid)."""
    bus = EventBus(data_dir=tmp_path)
    try:
        emitted = _emit_all(bus, _variants())
    finally:
        bus.close()
    assert all("id" in event for event in emitted)
    by_type = {event["type"]: event for event in emitted}
    assert by_type["status"]["id"] < 0
    assert by_type["notification_cleared"]["id"] < 0
    assert by_type["notification"]["id"] > 0


def test_variants_cover_the_tap_read_subset():
    """Pin the fixture to exactly the tap-read set (D11): a variant added or dropped here fails against
    the hardcoded contract, since the fixture no longer mirrors the full StreamEvent union."""
    variant_types = {event["type"] for event in _variants()}
    assert variant_types == set(_TAP_READ_TYPES)
    assert len(_variants()) == len(_TAP_READ_TYPES)
