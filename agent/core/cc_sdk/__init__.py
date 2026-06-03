"""cc_sdk — a tmux-backed reimplementation of the Claude Code agent SDK surface.

Vesta talks to Claude Code through this package exactly as it used to talk to the
official `claude_agent_sdk`: same message/block types, same hook plumbing, same
MCP-tool registration, same ClaudeSDKClient lifecycle. The difference is entirely
under the hood — `client.py` runs the real `claude` CLI interactively in tmux and
reconstructs the event stream from the session transcript and native hooks, rather
than speaking the headless control protocol.
"""

from .client import ClaudeSDKClient
from .mcp import McpServer, ToolDef, create_sdk_mcp_server, tool
from .messages import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    ContentBlock,
    HookContext,
    HookMatcher,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

__all__ = [
    "AssistantMessage",
    "ClaudeAgentOptions",
    "ClaudeSDKClient",
    "ClaudeSDKError",
    "ContentBlock",
    "HookContext",
    "HookMatcher",
    "McpServer",
    "Message",
    "RateLimitEvent",
    "RateLimitInfo",
    "ResultMessage",
    "SystemMessage",
    "TextBlock",
    "ThinkingBlock",
    "ToolDef",
    "ToolUseBlock",
    "create_sdk_mcp_server",
    "tool",
]
