"""Tests for the cc_sdk transport: helper scripts, config generation, parsing, usage."""

import json
import subprocess
import sys

import pytest

from core import cc_sdk
from core.cc_sdk import tmux as cc_tmux
from core.cc_sdk.client import _FORWARD, _MCP_STDIO, ClaudeSDKClient
from core.cc_sdk.messages import ClaudeAgentOptions
from core.cc_sdk.transcript import assistant_message_from, read_new_objects

# --- Helper scripts import cleanly when run by path (regression for the stdlib `types` shadow) ---


def test_forward_helper_runs_standalone_by_path():
    """_forward.py is stdlib-only and is launched by absolute path with PYTHONSAFEPATH=1;
    cc_sdk/types.py must not shadow stdlib `types`. With <2 args it prints {} and exits 0."""
    proc = subprocess.run([sys.executable, str(_FORWARD)], env={"PYTHONSAFEPATH": "1"}, capture_output=True, text=True, timeout=20)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "{}"
    assert "Traceback" not in proc.stderr


def test_mcp_stdio_helper_initializes_by_path():
    """_mcp_stdio.py answers an MCP initialize handshake without touching the bridge."""
    request = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    proc = subprocess.run(
        [sys.executable, str(_MCP_STDIO), "/tmp/cc_sdk_nonexistent.sock"],
        input=request + "\n",
        env={"PYTHONSAFEPATH": "1"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr
    reply = json.loads(proc.stdout.splitlines()[0])
    assert reply["id"] == 1
    assert reply["result"]["protocolVersion"] == "2025-06-18"


# --- Tool schemas exposed to claude must be valid (an invalid one kills the whole server) ---


def test_tooldef_normalizes_empty_schema():
    """A tool declared with `{}` (no "type") is invalid JSON Schema; Claude Code rejects the
    entire MCP server when any tool schema is malformed, so the agent's control tools silently
    vanish. ToolDef must normalize it to a valid object schema. This was THE first-start bug."""

    async def _noop(args):
        return {}

    empty = cc_sdk.tool("mark_setup_done", "marks done", {})(_noop)
    assert empty.input_schema == {"type": "object", "properties": {}}

    # A schema that is already valid is left untouched.
    valid = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    assert cc_sdk.tool("named", "x", valid)(_noop).input_schema == valid


# --- Generated config always carries the PYTHONSAFEPATH guard ---


def _new_client(tmp_path, **opts):
    return ClaudeSDKClient(options=ClaudeAgentOptions(cwd=str(tmp_path), **opts))


@pytest.mark.anyio
async def test_launch_raises_actionable_error_when_tmux_missing(tmp_path, monkeypatch):
    """A container rebuilt from a pre-tmux snapshot has no tmux on PATH; surface the fix
    instead of a bare FileNotFoundError raised deep in tmux.py."""
    monkeypatch.setattr("core.cc_sdk.client.shutil.which", lambda name: None)
    client = _new_client(tmp_path)
    with pytest.raises(RuntimeError, match="cc_sdk requires tmux"):
        await client._launch()


def test_hook_commands_carry_safepath_guard(tmp_path):
    client = _new_client(tmp_path, hooks={})
    client._write_config_files()
    settings = json.loads((client._workdir / "settings.json").read_text())
    # Suppresses the interactive bypass-mode acceptance dialog (blocks first-start as root otherwise).
    assert settings["skipDangerousModePermissionPrompt"] is True
    # SessionStart + Stop are always wired even with no user hooks.
    for entries in settings["hooks"].values():
        command = entries[0]["hooks"][0]["command"]
        assert command.startswith("PYTHONSAFEPATH=1 "), command


def test_mcp_config_carries_safepath_env(tmp_path):
    async def _noop(args):
        return {}

    server = cc_sdk.create_sdk_mcp_server("vesta", tools=[cc_sdk.tool("noop", "x", {"type": "object"})(_noop)])
    client = _new_client(tmp_path, mcp_servers={"vesta": server})
    client._bridge.register_tools(server.tools)
    client._write_config_files()
    mcp = json.loads((client._workdir / "mcp.json").read_text())
    server = mcp["mcpServers"]["vesta"]
    assert server["env"]["PYTHONSAFEPATH"] == "1"
    # Load the server's tools upfront so the agent's control tools aren't behind ToolSearch.
    assert server["alwaysLoad"] is True


# --- Turn/Stop counting: a late Stop from a prior turn must not end the next turn early ---


@pytest.mark.anyio
async def test_tmux_type_text_sends_random_literal_chunks(monkeypatch):
    calls: list[tuple[tuple[str, ...], bytes | None]] = []
    sleeps: list[float] = []
    chunk_sizes = [8, 12]

    async def record_run(socket: str, *args: str, stdin: bytes | None = None) -> tuple[int, str, str]:
        calls.append((args, stdin))
        return 0, "", ""

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    def randint(start: int, stop: int) -> int:
        return min(chunk_sizes.pop(0), stop)

    def uniform(start: float, stop: float) -> float:
        return start

    monkeypatch.setattr(cc_tmux, "_run", record_run)
    monkeypatch.setattr(cc_tmux.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(cc_tmux.random, "randint", randint)
    monkeypatch.setattr(cc_tmux.random, "uniform", uniform)

    await cc_tmux.type_text("sock", "session", "abcdefghijklmnop")

    assert calls == [
        (("send-keys", "-t", "session", "-l", "--", "\x1b[200~"), None),
        (("send-keys", "-t", "session", "-l", "--", "abcdefgh"), None),
        (("send-keys", "-t", "session", "-l", "--", "ijklmnop"), None),
        (("send-keys", "-t", "session", "-l", "--", "\x1b[201~"), None),
    ]
    assert sleeps == [0.0005]


@pytest.mark.anyio
async def test_tmux_submit_text_types_then_enters(monkeypatch):
    sent: list[tuple[str, str]] = []
    sleeps: list[float] = []

    async def record_type_text(socket: str, name: str, text: str) -> None:
        sent.append(("type", text))

    async def record_send_keys(socket: str, name: str, *keys: str) -> None:
        sent.append(("keys", " ".join(keys)))

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(cc_tmux, "type_text", record_type_text)
    monkeypatch.setattr(cc_tmux, "send_keys", record_send_keys)
    monkeypatch.setattr(cc_tmux.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(cc_tmux.random, "uniform", lambda start, stop: start)

    await cc_tmux.submit_text("sock", "session", "hello")

    assert sent == [("type", "hello"), ("keys", "Enter")]
    assert sleeps == [0.015]


@pytest.mark.anyio
async def test_tmux_submit_text_pastes_long_text_then_enters(monkeypatch):
    sent: list[tuple[str, str]] = []
    sleeps: list[float] = []
    text = "x" * (cc_tmux._PASTE_TEXT_CHARS + 1)

    async def record_type_text(socket: str, name: str, value: str) -> None:
        sent.append(("type", value))

    async def record_paste_text(socket: str, name: str, value: str) -> None:
        sent.append(("paste", value))

    async def record_send_keys(socket: str, name: str, *keys: str) -> None:
        sent.append(("keys", " ".join(keys)))

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(cc_tmux, "type_text", record_type_text)
    monkeypatch.setattr(cc_tmux, "paste_text", record_paste_text)
    monkeypatch.setattr(cc_tmux, "send_keys", record_send_keys)
    monkeypatch.setattr(cc_tmux.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(cc_tmux.random, "uniform", lambda start, stop: start)

    await cc_tmux.submit_text("sock", "session", text)

    assert sent == [("paste", text), ("keys", "Enter")]
    assert sleeps == [0.015]


@pytest.mark.anyio
async def test_query_submits_prompt(tmp_path, monkeypatch):
    sent: list[str] = []

    async def record_submit_text(socket: str, name: str, text: str) -> None:
        sent.append(text)

    monkeypatch.setattr("core.cc_sdk.client.tmux.submit_text", record_submit_text)
    client = _new_client(tmp_path)

    await client.query("hello")

    assert sent == ["hello"]


@pytest.mark.anyio
async def test_late_stop_does_not_complete_next_turn(tmp_path):
    """The Nth Stop completes the Nth turn. A leftover Stop from an abandoned turn only
    advances the count toward the current turn's threshold, never ending it prematurely."""
    client = _new_client(tmp_path)
    client._register_internal_hooks()
    on_stop = client._bridge.internal["Stop"][0]

    # Turn 1 was interrupted/abandoned without its Stop being consumed.
    client._turn_index = 1
    # Turn 2 starts.
    client._turn_index = 2
    threshold = client._turn_index

    # Turn 1's late Stop arrives.
    await on_stop({})
    assert client._stops_received < threshold, "turn 2 must not be considered complete yet"

    # Turn 2's own Stop arrives.
    await on_stop({})
    assert client._stops_received >= threshold, "turn 2 completes only on its own Stop"


# --- Interrupt: credits the abandoned turn's Stop and never fires Escapes at idle ---


@pytest.mark.anyio
async def test_interrupt_credits_missing_stop_and_double_escapes(tmp_path, monkeypatch):
    """An interrupted turn never fires its Stop hook (verified against real claude), so
    interrupt() must credit the missing Stop or every later turn hangs. The Escape must
    be sent twice — the TUI's escape parser swallows a lone ESC."""
    sent: list[tuple[str, ...]] = []

    async def record_send_keys(socket: str, name: str, *keys: str) -> None:
        sent.append(keys)

    monkeypatch.setattr("core.cc_sdk.client.tmux.send_keys", record_send_keys)
    client = _new_client(tmp_path)
    client._turn_index = 3
    client._stops_received = 2  # turns 1-2 completed, turn 3 in flight

    await client.interrupt()
    assert sent == [("Escape",), ("Escape",)]
    assert client._stops_received == 3


@pytest.mark.anyio
async def test_interrupt_at_idle_is_noop(tmp_path, monkeypatch):
    """When the current turn already completed, Escapes must not be sent: at idle a
    double-Escape opens the TUI's rewind dialog, and crediting another Stop would end
    the next turn prematurely."""
    sent: list[tuple[str, ...]] = []

    async def record_send_keys(socket: str, name: str, *keys: str) -> None:
        sent.append(keys)

    monkeypatch.setattr("core.cc_sdk.client.tmux.send_keys", record_send_keys)
    client = _new_client(tmp_path)
    client._turn_index = 3
    client._stops_received = 3  # turn 3 already completed

    await client.interrupt()
    assert sent == []
    assert client._stops_received == 3


# --- get_context_usage reports against the single window the caller supplied ---


@pytest.mark.anyio
async def test_context_usage_reports_configured_window(tmp_path):
    client = _new_client(tmp_path, context_window=1_000_000)
    client._last_usage = {"input_tokens": 160_000, "output_tokens": 10_000}
    usage = await client.get_context_usage()
    # The configured window is reported as-is, no conservative under-reporting.
    assert usage["maxTokens"] == 1_000_000
    assert usage["percentage"] == pytest.approx(17.0, abs=0.1)


@pytest.mark.anyio
async def test_context_usage_window_can_be_small(tmp_path):
    client = _new_client(tmp_path, context_window=200_000)
    client._last_usage = {"input_tokens": 160_000, "output_tokens": 10_000}
    usage = await client.get_context_usage()
    # 170k of a 200k window -> >80%, so the overflow warning can fire near the real limit.
    assert usage["maxTokens"] == 200_000
    assert usage["percentage"] > 80


# --- transcript parsing skips subagent (sidechain) lines ---


def test_assistant_message_skips_sidechain():
    main = {"type": "assistant", "isSidechain": False, "message": {"content": [{"type": "text", "text": "hi"}]}}
    sub = {"type": "assistant", "isSidechain": True, "message": {"content": [{"type": "text", "text": "secret"}]}}
    assert assistant_message_from(main) is not None
    assert assistant_message_from(sub) is None


def test_assistant_message_carries_api_error_flag():
    err = {
        "type": "assistant",
        "isApiErrorMessage": True,
        "message": {"content": [{"type": "text", "text": "API Error: 401 Invalid authentication credentials"}]},
    }
    normal = {"type": "assistant", "message": {"content": [{"type": "text", "text": "all good"}]}}
    err_message = assistant_message_from(err)
    assert err_message is not None
    assert err_message.is_api_error is True
    # Absent flag defaults to False, so an agent merely writing about a 401 isn't treated as one.
    normal_message = assistant_message_from(normal)
    assert normal_message is not None
    assert normal_message.is_api_error is False


def test_read_new_objects_only_consumes_complete_lines(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"type": "user"}) + "\n" + '{"partial":')
    objs, offset = read_new_objects(path, 0)
    assert len(objs) == 1
    # Offset stops at the end of the last complete line, so the partial line is re-read later.
    assert offset < path.stat().st_size


# --- Every hook event core registers is actually wired into claude's settings ---


def test_every_core_hook_event_is_wired(tmp_path):
    """Guards against the transport silently dropping an event core depends on: each event
    core.sdk_parsing.make_hooks registers must get a forward command in settings.json, and
    SessionStart/Stop are always wired even if core didn't ask for them."""
    from unittest.mock import MagicMock

    import core.sdk_parsing as sp

    core_events = set(sp.make_hooks(MagicMock()))
    assert "PreToolUse" in core_events and "Stop" in core_events  # sanity: make_hooks returned real events

    client = _new_client(tmp_path, hooks={event: [] for event in core_events})
    client._write_config_files()
    settings = json.loads((client._workdir / "settings.json").read_text())
    for event in core_events | {"SessionStart", "Stop"}:
        assert event in settings["hooks"], f"hook event {event} not wired into settings.json"
        command = settings["hooks"][event][0]["hooks"][0]["command"]
        assert _FORWARD.name in command and event in command


# --- pinned claude binary resolution (cc_sdk owns the version, not the host) ---


def test_claude_bin_override_skips_download(monkeypatch):
    from core.cc_sdk import _claude_bin

    monkeypatch.setenv("CC_SDK_CLAUDE_BIN", "/some/pinned/claude")
    # Must return the override verbatim without touching the network/platform detection.
    monkeypatch.setattr(_claude_bin, "_detect_platform", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    assert _claude_bin.ensure_claude() == "/some/pinned/claude"


def test_claude_bin_platform_string(monkeypatch):
    from core.cc_sdk import _claude_bin

    cases = {("Linux", "x86_64"): "linux-x64", ("Linux", "aarch64"): "linux-arm64", ("Darwin", "arm64"): "darwin-arm64"}
    for (system, machine), expected in cases.items():
        monkeypatch.setattr(_claude_bin.platform, "system", lambda s=system: s)
        monkeypatch.setattr(_claude_bin.platform, "machine", lambda m=machine: m)
        assert _claude_bin._detect_platform() == expected


# --- launch env: sandbox + pinned-version guards ---


@pytest.mark.anyio
async def test_launch_env_carries_sandbox_and_autoupdater_guards(tmp_path, monkeypatch):
    captured: dict[str, str] = {}

    async def fake_start_session(socket, name, *, cwd, command, **kwargs):
        captured["command"] = command

    monkeypatch.setattr("core.cc_sdk.client.tmux.start_session", fake_start_session)
    monkeypatch.setenv("CC_SDK_CLAUDE_BIN", "/usr/bin/true")  # skip the pinned-binary download
    client = _new_client(tmp_path)
    client._write_config_files()
    await client._launch()
    # bypassPermissions-as-root needs IS_SANDBOX; the pinned binary must not auto-update away.
    assert "IS_SANDBOX=1" in captured["command"]
    assert "DISABLE_AUTOUPDATER=1" in captured["command"]
    # And it launches the cc_sdk-resolved binary, not a bare `claude` from PATH.
    assert "/usr/bin/true" in captured["command"]


# --- thinking config maps to the env vars claude reads ---


def test_thinking_env_mapping():
    from core.cc_sdk.client import _thinking_env

    assert _thinking_env(ClaudeAgentOptions(thinking={"type": "enabled", "budget_tokens": 12345})) == {"MAX_THINKING_TOKENS": "12345"}
    assert _thinking_env(ClaudeAgentOptions(thinking={"type": "disabled"})) == {"CLAUDE_CODE_DISABLE_THINKING": "1"}
    # adaptive and unset both add nothing (claude's default behavior).
    assert _thinking_env(ClaudeAgentOptions(thinking={"type": "adaptive", "display": "x"})) == {}
    assert _thinking_env(ClaudeAgentOptions(thinking=None)) == {}


# --- bridge never lets a tool or hook failure break the turn ---


@pytest.mark.anyio
async def test_bridge_tool_exception_returns_error(tmp_path):
    from core.cc_sdk.bridge import Bridge

    async def _boom(args):
        raise RuntimeError("handler blew up")

    bridge = Bridge(socket_path=str(tmp_path / "b.sock"))
    bridge.register_tools([cc_sdk.tool("boom", "x", {"type": "object"})(_boom)])
    reply = await bridge._dispatch({"kind": "mcp", "op": "call", "name": "boom", "arguments": {}})
    assert "error" in reply and "handler blew up" in reply["error"]

    unknown = await bridge._dispatch({"kind": "mcp", "op": "call", "name": "missing", "arguments": {}})
    assert "error" in unknown and "missing" in unknown["error"]


@pytest.mark.anyio
async def test_bridge_hook_exception_is_swallowed(tmp_path):
    from core.cc_sdk.bridge import Bridge
    from core.cc_sdk.messages import HookMatcher

    async def _boom(payload, tool_use_id, context):
        raise RuntimeError("hook blew up")

    bridge = Bridge(socket_path=str(tmp_path / "b.sock"), hooks={"PreToolUse": [HookMatcher(hooks=[_boom])]})
    # A throwing hook callback must not propagate — the turn must survive.
    reply = await bridge._dispatch({"kind": "hook", "event": "PreToolUse", "payload": {"tool_name": "Bash"}})
    assert reply == {"output": {}}
