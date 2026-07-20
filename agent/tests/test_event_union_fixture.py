"""Event-union fixture emitter: serialize one instance of every StreamEvent variant plus a
SnapshotEvent through the real EventBus emit/read path into a committed JSON fixture, so Stage 4's
vestad aggregator test can parse the exact Python-to-Rust wire shape. Regenerate with
REGEN_EVENT_FIXTURES=1.
"""

import json
import os
import typing as tp
from pathlib import Path

from core.events import (
    AssistantEvent,
    ChatEvent,
    ErrorEvent,
    EventBus,
    NotificationClearedEvent,
    NotificationEvent,
    RateLimitedEvent,
    SnapshotEvent,
    StatusEvent,
    StreamEvent,
    SubagentStartEvent,
    SubagentStopEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserEvent,
)

# ts is a wall-clock value stamped inside emit; normalize it so the committed fixture is stable. The
# ids are the contract under test and are kept exactly as the real emit/read path produced them.
_FIXED_TS = "2026-01-01T00:00:00+00:00"

# user/chat are live-only in core now (Task 2); their durability moved to the app-chat skill, which
# stamps them with positive ids from its own store and broadcasts via emit_preformed. The fixture
# mirrors that real wire by emitting them through emit_preformed with explicit positive ids set well
# clear of the persisted rowid range so they read as skill-stamped, not core rowids.
_CHAT_ID_BASE = 1000
_PASS_THROUGH_TYPES: tuple[str, ...] = ("user", "chat")


def _variants() -> list[StreamEvent]:
    """One representative instance of every StreamEvent variant, in the TS union order. UserEvent
    carries intent_id and input_method so the seam exercises the send-message identity fields."""
    return [
        StatusEvent(type="status", state="thinking"),
        UserEvent(type="user", text="hello", input_method="typed", intent_id="intent-abc"),
        AssistantEvent(type="assistant", text="hi"),
        ThinkingEvent(type="thinking", text="hmm", signature="sig"),
        ChatEvent(type="chat", text="yo"),
        ToolStartEvent(type="tool_start", tool="Bash", input="ls", subagent=False),
        ToolEndEvent(type="tool_end", tool="Bash", subagent=False),
        ErrorEvent(type="error", text="oops"),
        RateLimitedEvent(type="rate_limited", text="Claude rate limit hit", window="five_hour", resets_at=1767225600),
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
        SubagentStartEvent(type="subagent_start", agent_id="abc", agent_type="browser"),
        SubagentStopEvent(type="subagent_stop", agent_id="abc", agent_type="browser"),
    ]


def _emit_all(bus: EventBus, variants: list[StreamEvent]) -> list[StreamEvent]:
    """Emit each variant so id is stamped the way the real wire does it: persisted variants through
    bus.emit (a positive rowid), status/notification_cleared through bus.emit (the negative live
    counter), and user/chat through bus.emit_preformed with a monotonic positive id (the app-chat
    skill's own stamp, passing straight through core). Normalize ts for a stable fixture."""
    emitted: list[StreamEvent] = []
    pass_through_id = _CHAT_ID_BASE
    for event in variants:
        if event["type"] in _PASS_THROUGH_TYPES:
            event["id"] = pass_through_id
            event["ts"] = _FIXED_TS
            bus.emit_preformed(event)
            pass_through_id += 1
        else:
            bus.emit(event)
            event["ts"] = _FIXED_TS
        emitted.append(event)
    return emitted


def _snapshot() -> SnapshotEvent:
    """Build the connect snapshot the way api.py does. app-chat is live-only in core now, so core no
    longer seeds the chat channel: the snapshot carries an empty chat page and the skill replays its
    own history. The snapshot is a frame, not an event, so it has no id of its own."""
    return SnapshotEvent(
        type="snapshot",
        state="idle",
        chat={"events": [], "cursor": None},
        notifications={"pending": ["whatsapp-123"]},
        config={"timezone": "America/New_York"},
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
    """Emit every event variant plus a snapshot through the real path and fail if the committed
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
    """The union covers all 13 variants and every one carries an id. status/notification_cleared are
    live-only through core's own emit (negative session ids); user/chat are stamped by the app-chat
    skill in the real wire, so the fixture emits them via emit_preformed with explicit positive ids
    (passed straight through, not core rowids); every remaining variant is persisted and carries a
    positive rowid."""
    bus = EventBus(data_dir=tmp_path)
    try:
        emitted = _emit_all(bus, _variants())
    finally:
        bus.close()
    assert len(emitted) == 13
    assert all("id" in event for event in emitted)
    by_type = {event["type"]: event for event in emitted}
    assert by_type["status"]["id"] < 0
    assert by_type["notification_cleared"]["id"] < 0
    assert by_type["user"]["id"] == _CHAT_ID_BASE
    assert by_type["chat"]["id"] == _CHAT_ID_BASE + 1
    persisted = [e for e in emitted if e["type"] not in ("status", "notification_cleared", *_PASS_THROUGH_TYPES)]
    assert all(e["id"] > 0 for e in persisted)


def test_variants_cover_the_stream_event_union():
    """Bind the hardcoded _variants() list to the authoritative StreamEvent union so a new variant
    added to core/events.py but forgotten here fails, instead of the count silently matching the
    list's own length. Each union member is a TypedDict whose `type` field is a single-literal, so
    the set of those literals is the exact set _variants() must produce."""
    members = tp.get_args(StreamEvent.__value__)
    union_types = {tp.get_args(member.__annotations__["type"])[0] for member in members}
    variant_types = {event["type"] for event in _variants()}
    assert len(_variants()) == len(members)
    assert variant_types == union_types
