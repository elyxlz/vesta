"""Fake interactive `claude` CLI driven by the cc_sdk e2e transport tests.

Stdlib only. Mimics the observable contract of the real TUI (verified against claude
v2.1.159 running in tmux) so the full cc_sdk machinery — tmux paste/keys, settings
hooks, _forward.py, the unix-socket bridge, _mcp_stdio.py, and transcript tailing —
is exercised end to end without credentials or network access.

Verified behaviors reproduced here:
  * argv contract: --session-id/--resume, --settings, --system-prompt-file,
    --mcp-config, --permission-mode, --model
  * refuses to start when onboarding/trust preseeding or the bypass-permissions
    settings flag is missing (the real TUI blocks on a dialog; this exits fast so
    tests fail in seconds rather than time out)
  * fires hooks from settings.json with realistic payloads
    (session_id, transcript_path, cwd, hook_event_name, ...)
  * appends transcript JSONL lines in the real shape, including non-assistant line
    types (user, system) that the parser must skip
  * input: bracketed paste + Enter submits; a lone ESC is buffered (never acts);
    a second ESC interrupts the in-flight turn WITHOUT firing a Stop hook
  * `tool:` prompts speak real JSON-RPC to the configured MCP stdio server

Prompt protocol (the test controls behavior through the prompt text):
  crash:<code>          write to stderr and exit with <code> mid-turn
  silent                never respond; only a (double) Escape ends the turn
  sidechain:<text>      emit a sidechain line with <text>, then a main "done" line
  think:<text>          emit a thinking block, then a text block
  tool:<name>:<json>    PreToolUse hook + tool_use block + MCP round trip + PostToolUse
  /compact[ <instr>]    PreCompact (trigger=manual) + isCompactSummary line + NO Stop hook
  anything else         echo the prompt back as `echo: <prompt>`
"""

import json
import os
import pathlib
import select
import subprocess
import sys
import tty
import typing
import uuid

PASTE_START = b"\x1b[200~"
PASTE_END = b"\x1b[201~"
ESC = b"\x1b"
USAGE = {"input_tokens": 100, "output_tokens": 25, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10}
INTERRUPT_NOTICE = "[Request interrupted by user]"


def parse_flags(argv: list[str]) -> dict[str, str]:
    flags: dict[str, str] = {}
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg.startswith("--") and index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            flags[arg[2:]] = argv[index + 1]
            index += 2
        elif arg.startswith("--"):
            flags[arg[2:]] = "true"
            index += 1
        else:
            index += 1
    return flags


def fail_startup(message: str, code: int) -> typing.NoReturn:
    sys.stderr.write(f"fake claude: {message}\n")
    sys.stderr.flush()
    sys.exit(code)


def check_preseed(settings: dict[str, typing.Any]) -> None:
    """The real TUI blocks on interactive dialogs when these are missing; exit fast instead."""
    claude_json = pathlib.Path("~/.claude.json").expanduser()
    if not claude_json.exists():
        fail_startup("would block on the onboarding dialog (~/.claude.json missing)", 11)
    config = json.loads(claude_json.read_text())
    if "hasCompletedOnboarding" not in config or not config["hasCompletedOnboarding"]:
        fail_startup("would block on the onboarding dialog (hasCompletedOnboarding not set)", 11)
    cwd = str(pathlib.Path.cwd())
    projects = config["projects"] if "projects" in config else {}
    entry = projects[cwd] if cwd in projects else {}
    if "hasTrustDialogAccepted" not in entry or not entry["hasTrustDialogAccepted"]:
        fail_startup(f"would block on the trust dialog (no trusted project entry for {cwd})", 12)
    if "skipDangerousModePermissionPrompt" not in settings or not settings["skipDangerousModePermissionPrompt"]:
        fail_startup("would block on the bypass-permissions acceptance dialog", 13)
    if os.geteuid() == 0 and "IS_SANDBOX" not in os.environ:
        fail_startup("refusing bypassPermissions as root without IS_SANDBOX=1", 14)


def fire_hook(ctx: dict[str, typing.Any], event: str, extra: dict[str, typing.Any]) -> None:
    settings = ctx["settings"]
    hooks = settings["hooks"] if "hooks" in settings else {}
    if event not in hooks:
        return
    payload: dict[str, typing.Any] = {
        "session_id": ctx["session_id"],
        "transcript_path": str(ctx["transcript"]),
        "cwd": str(pathlib.Path.cwd()),
        "permission_mode": ctx["permission_mode"],
        "hook_event_name": event,
    }
    payload.update(extra)
    for matcher in hooks[event]:
        for hook in matcher["hooks"]:
            subprocess.run(["sh", "-c", hook["command"]], input=json.dumps(payload).encode(), capture_output=True, timeout=30, check=False)


def write_line(ctx: dict[str, typing.Any], obj: dict[str, typing.Any]) -> None:
    with ctx["transcript"].open("a") as transcript:
        transcript.write(json.dumps(obj) + "\n")


def assistant_line(blocks: list[dict[str, typing.Any]], *, sidechain: bool = False, model: str = "fake-sonnet") -> dict[str, typing.Any]:
    return {
        "type": "assistant",
        "isSidechain": sidechain,
        "uuid": str(uuid.uuid4()),
        "message": {"role": "assistant", "model": model, "content": blocks, "usage": dict(USAGE)},
    }


def text_blocks(text: str) -> list[dict[str, typing.Any]]:
    return [{"type": "text", "text": text}]


def _mcp_session(ctx: dict[str, typing.Any]):
    """Open a JSON-RPC session to the configured MCP stdio server; returns (proc, rpc) or None."""
    if ctx["mcp_config"] is None:
        return None
    servers = ctx["mcp_config"]["mcpServers"]
    server = servers[sorted(servers)[0]]
    env = dict(os.environ)
    if "env" in server:
        env.update(server["env"])
    proc = subprocess.Popen([server["command"], *server["args"]], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=env, text=True)
    stdin, stdout = proc.stdin, proc.stdout
    if stdin is None or stdout is None:
        proc.kill()
        return None

    def rpc(method: str, params: dict[str, typing.Any], request_id: int | None = None) -> dict[str, typing.Any]:
        message: dict[str, typing.Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        stdin.write(json.dumps(message) + "\n")
        stdin.flush()
        if request_id is None:
            return {}
        return json.loads(stdout.readline())

    return proc, rpc


def call_mcp(ctx: dict[str, typing.Any], name: str, arguments: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Spawn the configured MCP stdio server and round-trip a tool call, like the real TUI."""
    session = _mcp_session(ctx)
    if session is None:
        return {"error": "no --mcp-config given"}
    proc, rpc = session
    rpc("initialize", {"protocolVersion": "2025-06-18"}, request_id=1)
    rpc("notifications/initialized", {})
    listed = rpc("tools/list", {}, request_id=2)
    called = rpc("tools/call", {"name": name, "arguments": arguments}, request_id=3)
    proc.stdin.close()
    proc.wait(timeout=10)
    return {"tools": listed["result"]["tools"], "result": called["result"]}


def submit(ctx: dict[str, typing.Any], prompt: str) -> None:
    fire_hook(ctx, "UserPromptSubmit", {"prompt": prompt})
    write_line(ctx, {"type": "user", "isSidechain": False, "message": {"role": "user", "content": prompt}})

    if prompt.startswith("crash:"):
        sys.stderr.write("fake claude: crashing on request\n")
        sys.stderr.flush()
        sys.exit(int(prompt.split(":", 1)[1]))

    if prompt == "silent":
        ctx["in_flight"] = True

    elif prompt.startswith("/compact"):
        # Manual /compact: fire PreCompact (trigger=manual), write the isCompactSummary line that
        # marks completion, and fire NO Stop hook — the exact contract cc_sdk.compact() waits on
        # (verified against real claude v2.1.16x: manual compaction never emits Stop and rewrites
        # the same session transcript in place).
        instructions = prompt[len("/compact") :].strip()
        fire_hook(ctx, "PreCompact", {"trigger": "manual", "custom_instructions": instructions})
        write_line(
            ctx,
            {
                "type": "user",
                "isSidechain": False,
                "isCompactSummary": True,
                "message": {"role": "user", "content": "[compacted conversation summary]"},
            },
        )
        ctx["in_flight"] = False

    elif prompt.startswith("hook:"):
        # hook:<EventName>:<extra-json> — fire one native hook event with the given extra
        # payload, then end the turn. Lets tests drive any event (PostToolUseFailure,
        # PreCompact, Notification, Subagent*, ...) through the real _forward.py -> bridge path.
        _, event, raw_extra = prompt.split(":", 2)
        extra = json.loads(raw_extra) if raw_extra.strip() else {}
        fire_hook(ctx, event, extra)
        write_line(ctx, assistant_line(text_blocks(f"fired {event}")))
        finish_turn(ctx, f"fired {event}")

    elif prompt.startswith("stderr:"):
        # Emit a line on stderr (which cc_sdk tails and routes to options.stderr) and finish.
        sys.stderr.write(prompt.split(":", 1)[1] + "\n")
        sys.stderr.flush()
        write_line(ctx, assistant_line(text_blocks("stderr written")))
        finish_turn(ctx, "stderr written")

    elif prompt.startswith("sidechain:"):
        write_line(ctx, assistant_line(text_blocks(prompt.split(":", 1)[1]), sidechain=True))
        write_line(ctx, assistant_line(text_blocks("done")))
        finish_turn(ctx, "done")

    elif prompt.startswith("think:"):
        text = prompt.split(":", 1)[1]
        blocks = [{"type": "thinking", "thinking": f"thinking about {text}", "signature": "fake-sig"}]
        write_line(ctx, assistant_line(blocks))
        write_line(ctx, assistant_line(text_blocks(text)))
        finish_turn(ctx, text)

    elif prompt.startswith("tool:"):
        _, name, raw_arguments = prompt.split(":", 2)
        arguments = json.loads(raw_arguments)
        tool_use_id = f"toolu_{uuid.uuid4().hex[:24]}"
        full_name = f"mcp__vesta__{name}"
        fire_hook(ctx, "PreToolUse", {"tool_name": full_name, "tool_input": arguments, "tool_use_id": tool_use_id})
        write_line(ctx, assistant_line([{"type": "tool_use", "id": tool_use_id, "name": full_name, "input": arguments}]))
        outcome = call_mcp(ctx, name, arguments)
        fire_hook(
            ctx,
            "PostToolUse",
            {"tool_name": full_name, "tool_input": arguments, "tool_response": outcome, "tool_use_id": tool_use_id, "duration_ms": 1},
        )
        text = f"tool says: {json.dumps(outcome)}"
        write_line(ctx, assistant_line(text_blocks(text)))
        finish_turn(ctx, text)

    else:
        text = f"echo: {prompt}"
        write_line(ctx, assistant_line(text_blocks(text)))
        finish_turn(ctx, text)


def finish_turn(ctx: dict[str, typing.Any], last_message: str) -> None:
    write_line(ctx, {"type": "system", "subtype": "turn_duration", "isSidechain": False, "durationMs": 100})
    fire_hook(ctx, "Stop", {"stop_hook_active": False, "last_assistant_message": last_message})
    ctx["in_flight"] = False


def on_interrupt(ctx: dict[str, typing.Any]) -> None:
    """A user interrupt aborts the in-flight turn and does NOT fire a Stop hook (verified)."""
    if not ctx["in_flight"]:
        return
    write_line(ctx, assistant_line(text_blocks(INTERRUPT_NOTICE), model="<synthetic>"))
    ctx["in_flight"] = False


def _paste_tail(buf: bytes) -> int:
    """Length of a partial PASTE_END marker at the end of buf (0 if none)."""
    for size in range(min(len(PASTE_END) - 1, len(buf)), 0, -1):
        if buf.endswith(PASTE_END[:size]):
            return size
    return 0


def read_loop(ctx: dict[str, typing.Any]) -> None:
    stdin_fd = sys.stdin.fileno()
    tty.setraw(stdin_fd)
    buf = b""
    pending = ""
    in_paste = False
    while True:
        ready, _, _ = select.select([stdin_fd], [], [], 0.5)
        if not ready:
            # A lone buffered ESC never acts on its own — exactly like the real TUI's
            # escape parser, which waits for a follow-up byte indefinitely.
            continue
        data = os.read(stdin_fd, 65536)
        if not data:
            return
        buf += data
        while buf:
            if in_paste:
                # tmux delivers pasted line breaks as CR (the way terminals send Enter);
                # like the real TUI, treat them as literal newlines inside the paste.
                end = buf.find(PASTE_END)
                if end != -1:
                    pending += buf[:end].decode(errors="replace").replace("\r", "\n")
                    buf = buf[end + len(PASTE_END) :]
                    in_paste = False
                    continue
                # Keep any partial end-marker suffix for the next read.
                tail = _paste_tail(buf)
                pending += buf[: len(buf) - tail].decode(errors="replace").replace("\r", "\n")
                buf = buf[len(buf) - tail :]
                break
            if buf.startswith(PASTE_START):
                buf = buf[len(PASTE_START) :]
                in_paste = True
                continue
            if buf.startswith(ESC):
                if PASTE_START.startswith(buf):
                    # Lone ESC or a partial paste-start marker: wait for a follow-up
                    # byte. A lone ESC therefore NEVER acts by itself — this is the
                    # real-TUI behavior that makes a single-Escape interrupt a no-op.
                    break
                # ESC followed by a byte that does not continue a paste marker: the ESC
                # finally flushes as a real Escape keypress (interrupting any in-flight
                # turn), and the remaining bytes are reprocessed.
                buf = buf[1:]
                on_interrupt(ctx)
                continue
            head, buf = buf[:1], buf[1:]
            if head in (b"\r", b"\n"):
                prompt, pending = pending, ""
                if prompt.strip():
                    submit(ctx, prompt)
                continue
            pending += head.decode(errors="replace")


def main() -> None:
    flags = parse_flags(sys.argv[1:])
    if "FAKE_CLAUDE_EXIT_ON_START" in os.environ:
        fail_startup("startup failure requested via FAKE_CLAUDE_EXIT_ON_START", int(os.environ["FAKE_CLAUDE_EXIT_ON_START"]))

    settings = json.loads(pathlib.Path(flags["settings"]).read_text()) if "settings" in flags else {}
    check_preseed(settings)

    resuming = "resume" in flags
    session_id = flags["resume"] if resuming else flags["session-id"]
    home = pathlib.Path.home()

    record_dir = home / ".fake_claude"
    record_dir.mkdir(exist_ok=True)
    with (record_dir / "argv.jsonl").open("a") as record:
        record.write(json.dumps(sys.argv[1:]) + "\n")

    project_dir = home / ".claude" / "projects" / str(pathlib.Path.cwd()).replace("/", "-")
    project_dir.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / f"{session_id}.jsonl"
    if not resuming:
        transcript.touch()
    elif not transcript.exists():
        fail_startup(f"--resume {session_id}: no such session transcript", 15)

    ctx: dict[str, typing.Any] = {
        "session_id": session_id,
        "settings": settings,
        "transcript": transcript,
        "permission_mode": flags["permission-mode"] if "permission-mode" in flags else "default",
        "mcp_config": json.loads(pathlib.Path(flags["mcp-config"]).read_text()) if "mcp-config" in flags else None,
        "in_flight": False,
    }

    # Request bracketed paste mode exactly like the real TUI. tmux only wraps
    # `paste-buffer -p` content in bracket codes when the application has asked for it,
    # so without this, pasted newlines submit line-by-line instead of staying in the box.
    sys.stdout.write("\x1b[?2004h")
    sys.stdout.flush()

    fire_hook(ctx, "SessionStart", {"source": "resume" if resuming else "startup", "model": flags["model"] if "model" in flags else "fake"})
    read_loop(ctx)


if __name__ == "__main__":
    main()
