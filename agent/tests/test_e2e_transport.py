"""End-to-end tests of the cc_sdk transport against a fake `claude` TUI in real tmux.

These exercise the full machinery the unit tests in test_cc_sdk.py cannot: a real tmux
server, bracketed paste + Enter submission, the real _forward.py hook command spawned by
the (fake) TUI, the unix-socket bridge, the real _mcp_stdio.py proxy, transcript tailing,
Stop counting, interrupts, crash detection, and resource cleanup.

The fake TUI (tests/fake_claude.py) reproduces behaviors verified against the real
claude v2.1.159: hook payload shapes, transcript line shapes, the escape parser that
swallows a lone ESC (so interrupts need a double Escape), and the absence of a Stop hook
for interrupted turns.
"""

import asyncio
import json
import os
import pathlib
import shutil
import sys
import time
import typing as tp

import pytest

from core import cc_sdk
from core.cc_sdk import tmux as cc_tmux
from core.cc_sdk.client import ClaudeSDKClient
from core.cc_sdk.messages import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
)

import fake_claude

_TMUX_MISSING = shutil.which("tmux") is None
if _TMUX_MISSING and "CI" in os.environ:
    # Never skip silently in CI: that would quietly drop all transport regression coverage.
    raise RuntimeError("tmux is required for the e2e transport tests in CI — install it in the workflow")
pytestmark = pytest.mark.skipif(_TMUX_MISSING, reason="tmux not available")

FAKE_CLAUDE_PATH = pathlib.Path(fake_claude.__file__).resolve()
TURN_TIMEOUT_S = 30.0


class Sandbox(tp.NamedTuple):
    home: pathlib.Path
    cwd: pathlib.Path


@pytest.fixture
def sandbox(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    """Isolated HOME plus a PATH shim so `claude` resolves to the fake TUI."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "claude"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{FAKE_CLAUDE_PATH}" "$@"\n')
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    # cc_sdk resolves a pinned claude binary; point it at the fake instead of downloading.
    monkeypatch.setenv("CC_SDK_CLAUDE_BIN", str(shim))
    cwd = tmp_path / "agent-cwd"
    cwd.mkdir()
    return Sandbox(home=home, cwd=cwd)


async def collect_response(client: ClaudeSDKClient) -> list[tp.Any]:
    messages = []
    async for message in client.receive_response():
        messages.append(message)
    return messages


async def collect_with_timeout(client: ClaudeSDKClient) -> list[tp.Any]:
    return await asyncio.wait_for(collect_response(client), timeout=TURN_TIMEOUT_S)


def texts_of(messages: list[tp.Any]) -> list[str]:
    return [block.text for m in messages if isinstance(m, AssistantMessage) for block in m.content if isinstance(block, TextBlock)]


async def wait_until(condition: tp.Callable[[], bool], *, timeout: float, message: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        await asyncio.sleep(0.1)
    raise AssertionError(message)


def recorded_argv(sandbox: Sandbox) -> list[list[str]]:
    return [json.loads(line) for line in (sandbox.home / ".fake_claude" / "argv.jsonl").read_text().splitlines()]


# --- Lifecycle ---


@pytest.mark.anyio
async def test_lifecycle_echo_roundtrip_and_cleanup(sandbox: Sandbox) -> None:
    """Startup -> preseed -> SessionStart over the bridge -> paste/Enter -> transcript tail
    -> Stop -> ResultMessage -> teardown leaves no tmux server, socket, or temp dir."""
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), system_prompt="e2e system prompt")
    client = ClaudeSDKClient(options=options)
    async with client:
        # _preseed_config wrote the onboarding/trust state the TUI requires (the fake
        # exits with a startup error if any of it is missing, so reaching this point
        # also proves the preseed). Assert the contents explicitly for clarity.
        preseed = json.loads((sandbox.home / ".claude.json").read_text())
        assert preseed["hasCompletedOnboarding"] is True
        cwd_entry = preseed["projects"][str(sandbox.cwd)]
        assert cwd_entry["hasTrustDialogAccepted"] is True

        await client.query("hello transport")
        messages = await collect_with_timeout(client)

        assert texts_of(messages) == ["echo: hello transport"]
        result = messages[-1]
        assert isinstance(result, ResultMessage)
        assert result.session_id == client.session_id
        assert result.duration_ms is not None

    workdir = client._workdir
    assert not workdir.exists(), "temp workdir must be removed on exit"
    assert not await cc_tmux.has_session(client._tmux_socket, client._tmux_session), "tmux server must be killed on exit"


@pytest.mark.anyio
async def test_multiline_prompt_survives_bracketed_paste(sandbox: Sandbox) -> None:
    """Newlines must stay inside the paste (one submission), not submit line-by-line."""
    prompt = "first line\nsecond line\nthird line"
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query(prompt)
        messages = await collect_with_timeout(client)
        assert texts_of(messages) == [f"echo: {prompt}"]


@pytest.mark.anyio
async def test_multi_turn_responses_are_isolated(sandbox: Sandbox) -> None:
    """Each turn only yields its own transcript lines (offset bookkeeping)."""
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query("first")
        first = await collect_with_timeout(client)
        assert texts_of(first) == ["echo: first"]

        await client.query("second")
        second = await collect_with_timeout(client)
        assert texts_of(second) == ["echo: second"], "second turn must not re-yield first turn output"

        first_result, second_result = first[-1], second[-1]
        assert isinstance(first_result, ResultMessage) and isinstance(second_result, ResultMessage)
        assert first_result.session_id == second_result.session_id == client.session_id


@pytest.mark.anyio
async def test_thinking_blocks_parsed(sandbox: Sandbox) -> None:
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query("think:deep thoughts")
        messages = await collect_with_timeout(client)
        thinking = [block for m in messages if isinstance(m, AssistantMessage) for block in m.content if isinstance(block, ThinkingBlock)]
        assert thinking and thinking[0].thinking == "thinking about deep thoughts"
        assert "deep thoughts" in texts_of(messages)


@pytest.mark.anyio
async def test_sidechain_lines_are_skipped(sandbox: Sandbox) -> None:
    """Subagent (isSidechain) transcript lines must never surface as main-agent messages."""
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query("sidechain:subagent secret")
        messages = await collect_with_timeout(client)
        all_text = " ".join(texts_of(messages))
        assert "subagent secret" not in all_text
        assert "done" in all_text


@pytest.mark.anyio
async def test_usage_flows_to_result_and_context_usage(sandbox: Sandbox) -> None:
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query("hello")
        messages = await collect_with_timeout(client)
        result = messages[-1]
        assert isinstance(result, ResultMessage)
        assert result.usage is not None and result.usage["input_tokens"] == fake_claude.USAGE["input_tokens"]

        usage = await client.get_context_usage()
        assert usage["totalTokens"] == sum(fake_claude.USAGE.values())
        assert usage["maxTokens"] == 200_000


# --- MCP tools and hooks ---


@pytest.mark.anyio
async def test_mcp_tool_roundtrip_runs_handler_in_process(sandbox: Sandbox) -> None:
    """claude -> _mcp_stdio.py -> bridge -> in-process handler -> result back to claude.

    Scope: this exercises OUR half of the MCP path (stdio proxy, bridge, handler dispatch)
    against the fake TUI. It does NOT model Claude Code's tool-search deferral, which is the
    real-claude behavior that hid these tools in production (the charbel bug). Only the live
    test (vestad/tests-integration/tests/live/mcp_tools.rs, real claude) covers that."""
    calls: list[dict[str, tp.Any]] = []

    @cc_sdk.tool("greet", "Greets a person", {"type": "object", "properties": {"name": {"type": "string"}}})
    async def greet(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        calls.append(args)
        return {"content": [{"type": "text", "text": f"hello {args['name']}"}]}

    server = cc_sdk.create_sdk_mcp_server("vesta", tools=[greet])
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), mcp_servers={"vesta": server})
    async with ClaudeSDKClient(options=options) as client:
        await client.query('tool:greet:{"name": "world"}')
        messages = await collect_with_timeout(client)

        # Handler ran inside this process (it mutated local state).
        assert calls == [{"name": "world"}]

        # The tool_use block surfaced through transcript parsing.
        tool_blocks = [block for m in messages if isinstance(m, AssistantMessage) for block in m.content if isinstance(block, ToolUseBlock)]
        assert tool_blocks and tool_blocks[0].name == "mcp__vesta__greet"
        assert tool_blocks[0].input == {"name": "world"}

        # The MCP stdio round trip returned the handler's output to the (fake) TUI.
        assert any("hello world" in text for text in texts_of(messages))


@pytest.mark.anyio
async def test_user_hooks_dispatched_through_bridge(sandbox: Sandbox) -> None:
    """Native command hooks -> _forward.py -> unix socket -> registered HookMatcher callbacks."""
    received: list[tuple[dict[str, tp.Any], tp.Any]] = []

    async def on_pre_tool_use(payload: dict[str, tp.Any], tool_use_id: tp.Any, context: tp.Any) -> dict[str, tp.Any]:
        received.append((payload, tool_use_id))
        return {}

    @cc_sdk.tool("noop", "Does nothing", {"type": "object"})
    async def noop(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        return {"content": [{"type": "text", "text": "ok"}]}

    server = cc_sdk.create_sdk_mcp_server("vesta", tools=[noop])
    options = ClaudeAgentOptions(
        cwd=str(sandbox.cwd),
        mcp_servers={"vesta": server},
        hooks={"PreToolUse": [HookMatcher(matcher="*", hooks=[on_pre_tool_use])]},
    )
    async with ClaudeSDKClient(options=options) as client:
        await client.query("tool:noop:{}")
        await collect_with_timeout(client)

    assert received, "PreToolUse hook must reach the registered HookMatcher"
    payload, tool_use_id = received[0]
    assert payload["hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "mcp__vesta__noop"
    assert isinstance(tool_use_id, str) and tool_use_id.startswith("toolu_")


# --- Interrupt (real-claude semantics: lone ESC is swallowed, no Stop hook on interrupt) ---


@pytest.mark.anyio
async def test_interrupt_unblocks_current_turn_and_next_turn_completes(sandbox: Sandbox) -> None:
    """interrupt() must (a) actually reach the TUI — a lone Escape is swallowed by its
    escape parser, so this catches any regression back to a single Escape — and (b) credit
    the interrupted turn's missing Stop so this turn AND every later turn still complete."""
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        await client.query("silent")
        transcript = client._transcript_path
        assert transcript is not None
        await wait_until(lambda: "silent" in transcript.read_text(), timeout=10, message="fake TUI never received the prompt")

        receive_task = asyncio.create_task(collect_response(client))
        await asyncio.sleep(0.5)
        assert not receive_task.done(), "turn must be genuinely in flight before interrupting"

        await client.interrupt()

        # (b) The fake fires NO Stop hook for the interrupted turn (verified real behavior),
        # so completion can only come from interrupt() crediting the missing Stop.
        messages = await asyncio.wait_for(receive_task, timeout=15)
        assert isinstance(messages[-1], ResultMessage)

        # (a) The double-Escape actually registered in the TUI.
        await wait_until(
            lambda: fake_claude.INTERRUPT_NOTICE in transcript.read_text(),
            timeout=10,
            message="the TUI never saw the interrupt — was a lone Escape sent?",
        )

        # The next turn must complete normally on its own single Stop.
        await client.query("after interrupt")
        messages = await collect_with_timeout(client)
        assert "echo: after interrupt" in texts_of(messages)
        assert isinstance(messages[-1], ResultMessage)


# --- Failure modes ---


@pytest.mark.anyio
async def test_crash_surfaces_sdk_error_with_stderr(sandbox: Sandbox) -> None:
    stderr_lines: list[str] = []
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), stderr=stderr_lines.append)
    async with ClaudeSDKClient(options=options) as client:
        # While alive, the liveness signal diagnostics.subprocess_alive reads is "no exit code yet".
        assert client.returncode is None

        await client.query("crash:7")
        with pytest.raises(ClaudeSDKError) as exc_info:
            await collect_with_timeout(client)
        assert "code 7" in str(exc_info.value)
        assert "crashing on request" in str(exc_info.value), "stderr tail must be included for diagnosis"

        # The crash exit code propagates to the returncode that the watchdog inspects.
        assert client.returncode == 7
        # Real stderr reaches the callback; the internal exit marker is consumed, not leaked.
        assert any("crashing on request" in line for line in stderr_lines)
        assert not any("__CC_EXIT__" in line for line in stderr_lines)


@pytest.mark.anyio
async def test_startup_failure_cleans_up_all_resources(sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed __aenter__ must not leak the tmux server, bridge socket, or temp dir."""
    monkeypatch.setenv("FAKE_CLAUDE_EXIT_ON_START", "12")
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    client = ClaudeSDKClient(options=options)
    with pytest.raises(ClaudeSDKError) as exc_info:
        await client.__aenter__()
    assert "during startup" in str(exc_info.value)
    assert "startup failure requested" in str(exc_info.value), "stderr tail must be included"

    assert not client._workdir.exists(), "temp workdir leaked"
    assert not pathlib.Path(client._sock_path).exists(), "bridge socket leaked"
    assert not await cc_tmux.has_session(client._tmux_socket, client._tmux_session), "tmux server leaked"


# --- Resume and CLI argument contract ---


@pytest.mark.anyio
async def test_resume_reuses_session_and_passes_resume_flag(sandbox: Sandbox) -> None:
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd))
    async with ClaudeSDKClient(options=options) as client:
        original_session = client.session_id
        await client.query("hello")
        await collect_with_timeout(client)

    resume_options = ClaudeAgentOptions(cwd=str(sandbox.cwd), resume=original_session)
    async with ClaudeSDKClient(options=resume_options) as resumed:
        assert resumed.session_id == original_session
        await resumed.query("again")
        messages = await collect_with_timeout(resumed)
        assert "echo: again" in texts_of(messages)
        result = messages[-1]
        assert isinstance(result, ResultMessage) and result.session_id == original_session

    launches = recorded_argv(sandbox)
    assert len(launches) == 2
    assert "--session-id" in launches[0] and "--resume" not in launches[0]
    assert "--resume" in launches[1]
    assert launches[1][launches[1].index("--resume") + 1] == original_session


@pytest.mark.anyio
async def test_cli_args_carry_options(sandbox: Sandbox) -> None:
    options = ClaudeAgentOptions(
        cwd=str(sandbox.cwd),
        system_prompt="THE SYSTEM PROMPT",
        model="opus",
        permission_mode="bypassPermissions",
        setting_sources=["user", "project"],
        betas=["context-1m-2025-08-07"],
    )
    async with ClaudeSDKClient(options=options) as client:
        argv = recorded_argv(sandbox)[0]
        assert argv[argv.index("--model") + 1] == "opus"
        assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
        assert argv[argv.index("--setting-sources") + 1] == "user,project"
        assert argv[argv.index("--betas") + 1] == "context-1m-2025-08-07"
        sysprompt_file = pathlib.Path(argv[argv.index("--system-prompt-file") + 1])
        assert sysprompt_file.read_text() == "THE SYSTEM PROMPT"
        assert argv[argv.index("--session-id") + 1] == client.session_id


@pytest.mark.anyio
async def test_cli_args_carry_add_dirs(sandbox: Sandbox) -> None:
    extra = str(sandbox.home)
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), add_dirs=[str(sandbox.cwd), extra])
    async with ClaudeSDKClient(options=options):
        argv = recorded_argv(sandbox)[0]
        add_dir_values = [argv[i + 1] for i, a in enumerate(argv) if a == "--add-dir"]
        assert str(sandbox.cwd) in add_dir_values and extra in add_dir_values


# --- All hook events core registers are dispatched through the bridge ---


@pytest.mark.anyio
async def test_all_core_hook_events_reach_bridge(sandbox: Sandbox) -> None:
    """core.sdk_parsing.make_hooks wires 9 events (PreToolUse, PostToolUse,
    PostToolUseFailure, SubagentStart/Stop, PreCompact, Notification, Stop, SessionStart).
    Only PreToolUse was covered before; this drives EVERY event core registers end to end
    (native command hook -> _forward.py -> bridge -> HookMatcher) so dropping any one is caught."""
    import core.sdk_parsing as sp
    from unittest.mock import MagicMock

    core_events = [e for e in sp.make_hooks(MagicMock()) if e != "Stop"]  # Stop fires on every turn end
    received: dict[str, dict[str, tp.Any]] = {}

    def matcher_for(event: str) -> HookMatcher:
        async def cb(payload: dict[str, tp.Any], tool_use_id: tp.Any, context: tp.Any) -> dict[str, tp.Any]:
            received[event] = payload
            return {}

        return HookMatcher(matcher="*", hooks=[cb])

    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), hooks={event: [matcher_for(event)] for event in core_events})
    # Representative payloads for the fields core's callbacks actually read.
    extras = {
        "PostToolUseFailure": {"tool_name": "Bash", "error": "boom"},
        "PreCompact": {"trigger": "auto"},
        "Notification": {"notification_type": "info", "title": "t", "message": "m"},
        "SubagentStart": {"agent_type": "explorer"},
        "SubagentStop": {"agent_type": "explorer"},
        "PostToolUse": {"tool_name": "Bash", "tool_response": "ok"},
        "PreToolUse": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "tool_use_id": "toolu_x"},
    }
    async with ClaudeSDKClient(options=options) as client:
        for event in core_events:
            extra = extras.get(event, {})
            await client.query(f"hook:{event}:{json.dumps(extra)}")
            await collect_with_timeout(client)

    for event in core_events:
        assert event in received, f"hook event {event} never reached its HookMatcher"
        assert received[event]["hook_event_name"] == event
    # Payload fidelity for the fields core reads off the heaviest events.
    assert received["PostToolUseFailure"]["error"] == "boom"
    assert received["PostToolUse"]["tool_response"] == "ok"
    assert received["PreCompact"]["trigger"] == "auto"
    assert received["Notification"]["message"] == "m"


@pytest.mark.anyio
async def test_stderr_callback_receives_output(sandbox: Sandbox) -> None:
    """core wires options.stderr to surface agent-side diagnostics; lines on the claude
    process's stderr must reach that callback."""
    stderr_lines: list[str] = []
    options = ClaudeAgentOptions(cwd=str(sandbox.cwd), stderr=stderr_lines.append)
    async with ClaudeSDKClient(options=options) as client:
        await client.query("stderr:DIAGNOSTIC_MARKER_42")
        await collect_with_timeout(client)
        await wait_until(
            lambda: any("DIAGNOSTIC_MARKER_42" in line for line in stderr_lines),
            timeout=5,
            message="stderr line never reached the options.stderr callback",
        )
