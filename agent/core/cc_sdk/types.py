"""Static types mirroring the public surface of the official claude_agent_sdk.

These exist so the rest of the agent can keep its type hints and `cast()` sites
unchanged while the transport underneath drives the `claude` CLI in tmux. The
TypedDicts are plain dicts at runtime; only the dataclasses carry behaviour.
"""

import dataclasses as dc
import typing as tp

HookEvent = tp.Literal[
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "Notification",
    "Stop",
]

# Hook stdin payloads are passed through verbatim from the `claude` CLI, so these
# are intentionally permissive (total=False) — every field is read with `in` guards.


class PreToolUseHookInput(tp.TypedDict, total=False):
    session_id: str
    cwd: str
    hook_event_name: str
    tool_name: str
    tool_input: dict[str, tp.Any]
    tool_use_id: str
    agent_id: str
    agent_type: str


class PostToolUseHookInput(tp.TypedDict, total=False):
    session_id: str
    cwd: str
    hook_event_name: str
    tool_name: str
    tool_input: dict[str, tp.Any]
    tool_response: tp.Any
    tool_use_id: str
    agent_id: str
    agent_type: str


class PostToolUseFailureHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    tool_name: str
    error: str
    tool_use_id: str
    agent_id: str
    agent_type: str


class SubagentStartHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    agent_id: str
    agent_type: str


class SubagentStopHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    agent_id: str
    agent_type: str


class PreCompactHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    trigger: str


class NotificationHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    notification_type: str
    title: str
    message: str


class StopHookInput(tp.TypedDict, total=False):
    session_id: str
    hook_event_name: str
    stop_hook_active: bool
    last_assistant_message: str


class SessionStartHookInput(tp.TypedDict, total=False):
    session_id: str
    transcript_path: str
    cwd: str
    hook_event_name: str
    source: str
    model: str


HookJSONOutput = dict[str, tp.Any]
HookCallback = tp.Callable[..., tp.Awaitable[HookJSONOutput]]


# --- Thinking config (TypedDicts, so pydantic validates them structurally) ---


class ThinkingConfigAdaptive(tp.TypedDict):
    type: tp.Literal["adaptive"]
    display: str


class ThinkingConfigEnabled(tp.TypedDict):
    type: tp.Literal["enabled"]
    budget_tokens: int


class ThinkingConfigDisabled(tp.TypedDict):
    type: tp.Literal["disabled"]


ThinkingConfig = ThinkingConfigAdaptive | ThinkingConfigEnabled | ThinkingConfigDisabled


@dc.dataclass
class ToolPermissionContext:
    """Context passed to a can_use_tool callback. Unused under bypassPermissions."""

    suggestions: list[tp.Any] = dc.field(default_factory=list)


@dc.dataclass
class PermissionResultAllow:
    behavior: tp.Literal["allow"] = "allow"
