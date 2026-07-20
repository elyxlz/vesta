"""Event type contract tests: every StreamEvent/HistoryEvent variant round-trips through json and the bus.

The single source of truth is the StreamEvent/HistoryEvent TypedDicts in core.events; these tests hold a
representative instance of every variant to json serialization and EventBus persistence.
"""

import json
import typing as tp

from core.events import (
    _LIVE_ONLY_TYPES,
    AssistantEvent,
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
)

# One representative instance of every StreamEvent variant, then HistoryEvent (which nests them).
# Every required field is populated with a value of the correct type so the web's `satisfies` check
# catches both field-name and field-type drift.
_STREAM_FIXTURES: list[tp.Any] = [
    StatusEvent(type="status", ts="2026-01-01T00:00:00Z", state="thinking"),
    AssistantEvent(type="assistant", ts="2026-01-01T00:00:00Z", text="hi"),
    ThinkingEvent(type="thinking", ts="2026-01-01T00:00:00Z", text="hmm", signature="sig"),
    ToolStartEvent(type="tool_start", ts="2026-01-01T00:00:00Z", tool="Bash", input="ls", subagent=False),
    ToolEndEvent(type="tool_end", ts="2026-01-01T00:00:00Z", tool="Bash", subagent=False),
    ErrorEvent(type="error", ts="2026-01-01T00:00:00Z", text="oops"),
    RateLimitedEvent(type="rate_limited", ts="2026-01-01T00:00:00Z", text="Claude rate limit hit", window="five_hour", resets_at=1767225600),
    NotificationEvent(type="notification", ts="2026-01-01T00:00:00Z", source="email", summary="new mail"),
    NotificationClearedEvent(type="notification_cleared", ts="2026-01-01T00:00:00Z", notif_id="email-123"),
    SubagentStartEvent(type="subagent_start", ts="2026-01-01T00:00:00Z", agent_id="abc", agent_type="browser"),
    SubagentStopEvent(type="subagent_stop", ts="2026-01-01T00:00:00Z", agent_id="abc", agent_type="browser"),
]

# The connect snapshot wraps current state under domain objects; it has no `ts` (not a streamed
# event). Chat is not on the snapshot (the app-chat skill owns it); `notifications.pending` is the
# on-disk id seed.
_SNAPSHOT_FIXTURE: SnapshotEvent = SnapshotEvent(
    type="snapshot",
    state="idle",
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

    # The live-only types (status, notification_cleared) are transient live signals, intentionally not
    # persisted (see EventBus.emit and _LIVE_ONLY_TYPES).
    persistable = [event for event in _STREAM_FIXTURES if event["type"] not in _LIVE_ONLY_TYPES]
    for event in persistable:
        bus.emit(event)

    stored, _ = bus.recent(limit=len(persistable) + 1)
    stored_types = {stored_event["type"] for stored_event in stored}

    for event in persistable:
        assert event["type"] in stored_types, f"{event['type']} not found in stored events"

    bus.close()
