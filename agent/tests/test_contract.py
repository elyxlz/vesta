"""Event type contract tests: every StreamEvent/HistoryEvent variant round-trips through json and the bus.

The single source of truth is the StreamEvent/HistoryEvent TypedDicts in core.events; these tests hold a
representative instance of every variant to json serialization and EventBus persistence.
"""

import json
import typing as tp

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
    SubagentStartEvent,
    SubagentStopEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserEvent,
)

# One representative instance of every StreamEvent variant, then HistoryEvent (which nests them).
# Every required field is populated with a value of the correct type so the web's `satisfies` check
# catches both field-name and field-type drift.
_STREAM_FIXTURES: list[tp.Any] = [
    StatusEvent(type="status", ts="2026-01-01T00:00:00Z", state="thinking"),
    UserEvent(type="user", ts="2026-01-01T00:00:00Z", text="hello", input_method="typed"),
    AssistantEvent(type="assistant", ts="2026-01-01T00:00:00Z", text="hi"),
    ThinkingEvent(type="thinking", ts="2026-01-01T00:00:00Z", text="hmm", signature="sig"),
    ChatEvent(type="chat", ts="2026-01-01T00:00:00Z", text="yo"),
    ToolStartEvent(type="tool_start", ts="2026-01-01T00:00:00Z", tool="Bash", input="ls", subagent=False),
    ToolEndEvent(type="tool_end", ts="2026-01-01T00:00:00Z", tool="Bash", subagent=False),
    ErrorEvent(type="error", ts="2026-01-01T00:00:00Z", text="oops"),
    RateLimitedEvent(type="rate_limited", ts="2026-01-01T00:00:00Z", text="Claude rate limit hit", window="five_hour", resets_at=1767225600),
    NotificationEvent(type="notification", ts="2026-01-01T00:00:00Z", source="email", summary="new mail"),
    NotificationClearedEvent(type="notification_cleared", ts="2026-01-01T00:00:00Z", notif_id="email-123"),
    SubagentStartEvent(type="subagent_start", ts="2026-01-01T00:00:00Z", agent_id="abc", agent_type="browser"),
    SubagentStopEvent(type="subagent_stop", ts="2026-01-01T00:00:00Z", agent_id="abc", agent_type="browser"),
]

# The connect snapshot wraps the stream events under domain objects; it has no `ts` (not a streamed
# event). `chat.events` nests StreamEvents; `notifications.pending` is the on-disk id seed.
_SNAPSHOT_FIXTURE: SnapshotEvent = SnapshotEvent(
    type="snapshot",
    state="idle",
    chat={
        "events": [
            StatusEvent(type="status", ts="2026-01-01T00:00:00Z", state="idle"),
            AssistantEvent(type="assistant", ts="2026-01-01T00:00:00Z", text="hi"),
        ],
        "cursor": 42,
    },
    notifications={"pending": ["email-123"]},
    config={"timezone": "America/New_York"},
)

def test_all_stream_events_serializable():
    """Every event fixture round-trips through json without loss of its type tag."""
    for event in [*_STREAM_FIXTURES, _SNAPSHOT_FIXTURE]:
        serialized = json.dumps(event)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip["type"] == event["type"]


def test_eventbus_roundtrip_all_types(tmp_path):
    """Emit each persistable event type, read back, verify the type tag survives."""
    bus = EventBus(data_dir=tmp_path)

    # `status` and `notification_cleared` are transient live signals, intentionally not persisted
    # (see EventBus.emit).
    persistable = [event for event in _STREAM_FIXTURES if event["type"] not in ("status", "notification_cleared")]
    for event in persistable:
        bus.emit(event)

    stored, _ = bus.recent(limit=len(persistable) + 1)
    stored_types = {stored_event["type"] for stored_event in stored}

    for event in persistable:
        assert event["type"] in stored_types, f"{event['type']} not found in stored events"

    bus.close()
