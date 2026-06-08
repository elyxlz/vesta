"""Message/block dataclasses, options, and hook plumbing types.

The message and block classes mirror the official SDK so that `isinstance` checks
and attribute access in core.sdk_parsing keep working unchanged. Fields that the
parser reads defensively (ResultMessage.session_id, .usage, ...) deliberately have
no class-level defaults, so a `MagicMock(spec=ResultMessage)` raises AttributeError
on unset access exactly like the real type — the parser relies on that.
"""

import dataclasses as dc
import pathlib as pl
import typing as tp

from .types import HookCallback, HookEvent, ThinkingConfig


class ClaudeSDKError(Exception):
    """Base error raised by the transport (resume failure, CLI crash, timeouts)."""


# --- Content blocks ---


@dc.dataclass
class TextBlock:
    text: str


@dc.dataclass
class ThinkingBlock:
    thinking: str
    signature: str


@dc.dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, tp.Any]


ContentBlock = TextBlock | ThinkingBlock | ToolUseBlock


# --- Messages ---


@dc.dataclass
class AssistantMessage:
    content: list[ContentBlock]
    model: str | None = None


@dc.dataclass
class RateLimitInfo:
    status: str
    utilization: float
    rate_limit_type: str


@dc.dataclass
class RateLimitEvent:
    rate_limit_info: RateLimitInfo


@dc.dataclass
class SystemMessage:
    subtype: str
    data: dict[str, tp.Any]


@dc.dataclass
class ResultMessage:
    session_id: str | None
    usage: dict[str, tp.Any] | None
    total_cost_usd: float | None
    duration_ms: float | None
    content: list[tp.Any] = dc.field(default_factory=list)


Message = AssistantMessage | ResultMessage | SystemMessage | RateLimitEvent


# --- Hooks ---


@dc.dataclass
class HookContext:
    """Opaque context handed to hook callbacks. Empty, like the SDK's."""


@dc.dataclass
class HookMatcher:
    matcher: str | None = None
    hooks: list[HookCallback] = dc.field(default_factory=list)


# --- Client options ---


@dc.dataclass
class ClaudeAgentOptions:
    system_prompt: str | None = None
    model: str | None = None
    betas: list[str] = dc.field(default_factory=list)
    # Effective context window, when the user has chosen one. Drives the context-usage
    # percentage; None falls back to the 200k/1M heuristic. claude-code itself is told
    # via CLAUDE_CODE_MAX_CONTEXT_TOKENS in the launch env (see client.build_client_options).
    max_context_tokens: int | None = None
    hooks: dict[HookEvent, list[HookMatcher]] = dc.field(default_factory=dict)
    permission_mode: str = "default"
    can_use_tool: tp.Callable[..., tp.Any] | None = None
    cwd: pl.Path | str | None = None
    setting_sources: list[str] = dc.field(default_factory=list)
    add_dirs: list[str] = dc.field(default_factory=list)
    thinking: ThinkingConfig | None = None
    max_buffer_size: int | None = None
    stderr: tp.Callable[[str], None] | None = None
    mcp_servers: dict[str, tp.Any] = dc.field(default_factory=dict)
    resume: str | None = None
    # Extra env vars scoped to the claude subprocess only (not os.environ), so e.g. the
    # OpenRouter base-url/context overrides don't leak into the skill subprocesses the
    # agent spawns. Merged into the launch env after the fixed defaults.
    env: dict[str, str] = dc.field(default_factory=dict)
    # "all" enables the Skill tool for every skill discovered via setting_sources.
    # Interactive Claude Code already does this by default, so the value is accepted
    # for parity but needs no extra CLI flag.
    skills: str | None = None
