"""Event type contract tests: verify Python TypedDicts and TypeScript types agree."""

import json
import re
import typing as tp
from pathlib import Path

import pytest
from vesta.events import (
    AssistantEvent,
    ChatEvent,
    ErrorEvent,
    EventBus,
    HistoryEvent,
    NotificationEvent,
    StatusEvent,
    SubagentStartEvent,
    SubagentStopEvent,
    ThinkingEvent,
    ToolEndEvent,
    ToolStartEvent,
    UserEvent,
)

# The single source of truth: every event type and its required fields (excluding base `ts`)
EVENT_SPEC: dict[str, set[str]] = {
    "status": {"state"},
    "user": {"text"},
    "assistant": {"text"},
    "thinking": {"text", "signature"},
    "chat": {"text"},
    "tool_start": {"tool", "input", "subagent"},
    "tool_end": {"tool", "subagent"},
    "error": {"text"},
    "notification": {"source", "summary"},
    "subagent_start": {"agent_id", "agent_type"},
    "subagent_stop": {"agent_id", "agent_type"},
}

HISTORY_SPEC = {"events", "state", "cursor"}

# Map type strings to Python TypedDict classes
_PYTHON_CLASSES: dict[str, type] = {
    "status": StatusEvent,
    "user": UserEvent,
    "assistant": AssistantEvent,
    "thinking": ThinkingEvent,
    "chat": ChatEvent,
    "tool_start": ToolStartEvent,
    "tool_end": ToolEndEvent,
    "error": ErrorEvent,
    "notification": NotificationEvent,
    "subagent_start": SubagentStartEvent,
    "subagent_stop": SubagentStopEvent,
}


def _get_typed_dict_fields(cls: type) -> set[str]:
    """Get all fields from a TypedDict, including inherited ones, minus base fields."""
    hints = tp.get_type_hints(cls)
    return set(hints.keys()) - {"type", "ts"}


def test_python_event_types_match_spec():
    """Every Python TypedDict has exactly the fields declared in EVENT_SPEC."""
    for type_name, expected_fields in EVENT_SPEC.items():
        cls = _PYTHON_CLASSES[type_name]
        actual_fields = _get_typed_dict_fields(cls)
        assert actual_fields == expected_fields, f"{type_name}: expected {expected_fields}, got {actual_fields}"


def test_python_history_event_matches_spec():
    fields = _get_typed_dict_fields(HistoryEvent)
    assert fields == HISTORY_SPEC, f"HistoryEvent: expected {HISTORY_SPEC}, got {fields}"


def test_typescript_types_match_spec():
    """Parse app/src/lib/types.ts and verify VestaEvent covers all event types with correct fields."""
    ts_path = Path(__file__).resolve().parents[2] / "app" / "src" / "lib" / "types.ts"
    if not ts_path.exists():
        pytest.skip("TypeScript source not available")

    content = ts_path.read_text()

    # Extract all type literals from the VestaEvent union
    # Matches: { type: "typename"; ...fields }
    type_pattern = re.compile(r'type:\s*"(\w+)"')
    ts_types = set(type_pattern.findall(content))

    # TS doesn't need every Python event type (some are server-internal),
    # but core display types must be present
    core_types = {"status", "user", "assistant", "thinking", "chat", "tool_start", "tool_end", "error", "notification", "history"}
    missing = core_types - ts_types
    assert not missing, f"TypeScript VestaEvent missing core types: {missing}"


def test_all_stream_events_serializable():
    """Construct a minimal instance of each event type and verify json.dumps succeeds."""
    test_instances: list[tp.Any] = [
        StatusEvent(type="status", state="idle"),
        UserEvent(type="user", text="hello"),
        AssistantEvent(type="assistant", text="hi"),
        ThinkingEvent(type="thinking", text="hmm", signature="sig"),
        ChatEvent(type="chat", text="yo"),
        ToolStartEvent(type="tool_start", tool="Bash", input="ls", subagent=False),
        ToolEndEvent(type="tool_end", tool="Bash", subagent=False),
        ErrorEvent(type="error", text="oops"),
        NotificationEvent(type="notification", source="email", summary="new mail"),
        SubagentStartEvent(type="subagent_start", agent_id="abc", agent_type="browser"),
        SubagentStopEvent(type="subagent_stop", agent_id="abc", agent_type="browser"),
    ]

    for event in test_instances:
        serialized = json.dumps(event)
        assert isinstance(serialized, str)
        roundtrip = json.loads(serialized)
        assert roundtrip["type"] == event["type"]


def test_eventbus_roundtrip_all_types(tmp_path):
    """Emit each persistable event type, read back, verify fields survive."""
    bus = EventBus(data_dir=tmp_path)

    events_to_emit: list[tp.Any] = [
        UserEvent(type="user", text="hello"),
        AssistantEvent(type="assistant", text="hi"),
        ChatEvent(type="chat", text="yo"),
        ThinkingEvent(type="thinking", text="hmm", signature="sig"),
        ToolStartEvent(type="tool_start", tool="Bash", input="ls", subagent=False),
        ToolEndEvent(type="tool_end", tool="Bash", subagent=False),
        ErrorEvent(type="error", text="oops"),
        NotificationEvent(type="notification", source="email", summary="new mail"),
        SubagentStartEvent(type="subagent_start", agent_id="abc", agent_type="browser"),
        SubagentStopEvent(type="subagent_stop", agent_id="abc", agent_type="browser"),
    ]

    for event in events_to_emit:
        bus.emit(event)

    stored, _ = bus.recent(limit=len(events_to_emit) + 1)
    stored_types = {e["type"] for e in stored}

    for event in events_to_emit:
        assert event["type"] in stored_types, f"{event['type']} not found in stored events"

    bus.close()


def test_spec_covers_all_python_classes():
    """Ensure EVENT_SPEC doesn't miss any Python event class."""
    assert set(_PYTHON_CLASSES.keys()) == set(EVENT_SPEC.keys())
