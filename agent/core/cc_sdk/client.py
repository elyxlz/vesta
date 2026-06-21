"""ClaudeSDKClient — drives an interactive `claude` session inside a private tmux.

Drop-in replacement for the official SDK client. Instead of speaking the control
protocol to a headless subprocess, it:

  * launches `claude` (the real TUI) in a dedicated tmux server,
  * submits prompts by typing randomized bracketed-paste chunks and pressing Enter,
  * streams the assistant's reply by tailing the session transcript JSONL,
  * receives tool/subagent/compaction events as native command hooks routed through
    a unix-socket bridge, and exposes the agent's MCP tools via a stdio proxy,
  * interrupts by sending a double Escape (a lone ESC is swallowed by the TUI's
    escape-sequence parser).

The public surface (query / receive_response / interrupt / get_context_usage /
session_id / async context manager) matches what core/ already calls.
"""

import asyncio
import json
import os
import pathlib as pl
import shlex
import shutil
import sys
import tempfile
import time
import typing as tp
import uuid

from . import transcript
from . import tmux
from ._claude_bin import ensure_claude
from .bridge import Bridge
from .messages import ClaudeAgentOptions, ClaudeSDKError, ResultMessage
from .mcp import McpServer

_PKG_DIR = pl.Path(__file__).resolve().parent
_FORWARD = _PKG_DIR / "_forward.py"
_MCP_STDIO = _PKG_DIR / "_mcp_stdio.py"

_EXIT_MARKER = "__CC_EXIT__:"
_STARTUP_TIMEOUT_S = 120.0
_POLL_S = 0.15
_POST_STOP_DRAIN_S = 2.5
# Manual /compact fires PreCompact but never a Stop hook, and the summarization request
# between them can run for tens of seconds with no transcript writes — so completion is the
# isCompactSummary transcript line, not quiescence. Both waits are deliberately generous: the
# nightly restart that drives compact() is not latency sensitive, and a full day-sized context
# summarizes slowly. Erring long only costs a wait before restarting if compaction truly hangs;
# erring short would abandon a still-running compaction and restart on the un-compacted session.
_COMPACT_START_TIMEOUT_S = 60.0
_COMPACT_TIMEOUT_S = 900.0
_ALWAYS_EVENTS = ("SessionStart", "Stop", "PreCompact")


def _preseed_config(cwd: str) -> None:
    """Make a fresh interactive session skip onboarding and the workspace trust dialog."""
    path = pl.Path(os.path.expanduser("~/.claude.json"))
    data: dict[str, tp.Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    data["hasCompletedOnboarding"] = True
    projects = data["projects"] if "projects" in data and isinstance(data["projects"], dict) else {}
    entry = projects[cwd] if cwd in projects and isinstance(projects[cwd], dict) else {}
    entry["hasTrustDialogAccepted"] = True
    entry["hasCompletedProjectOnboarding"] = True
    projects[cwd] = entry
    data["projects"] = projects
    tmp = path.with_suffix(".json.cctmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _thinking_env(options: ClaudeAgentOptions) -> dict[str, str]:
    thinking = options.thinking
    if not isinstance(thinking, dict) or "type" not in thinking:
        return {}
    data = tp.cast("dict[str, tp.Any]", thinking)
    kind = data["type"]
    if kind == "disabled":
        return {"CLAUDE_CODE_DISABLE_THINKING": "1"}
    if kind == "enabled" and "budget_tokens" in data:
        return {"MAX_THINKING_TOKENS": str(data["budget_tokens"])}
    return {}


def _claude_args(
    options: ClaudeAgentOptions,
    *,
    claude_bin: str,
    session_id: str,
    resuming: bool,
    sysprompt_file: pl.Path,
    settings_file: pl.Path,
    mcp_file: pl.Path | None,
) -> list[str]:
    args = [claude_bin]
    if resuming:
        args += ["--resume", session_id]
    else:
        args += ["--session-id", session_id]
    args += ["--permission-mode", options.permission_mode or "bypassPermissions"]
    if options.model:
        args += ["--model", options.model]
    args += ["--system-prompt-file", str(sysprompt_file)]
    args += ["--settings", str(settings_file)]
    if options.setting_sources:
        args += ["--setting-sources", ",".join(options.setting_sources)]
    if mcp_file is not None:
        args += ["--mcp-config", str(mcp_file)]
    for d in options.add_dirs:
        args += ["--add-dir", d]
    for beta in options.betas:
        args += ["--betas", beta]
    return args


class ClaudeSDKClient:
    def __init__(self, *, options: ClaudeAgentOptions) -> None:
        self._options = options
        self._session_id = options.resume if options.resume else str(uuid.uuid4())
        self._resuming = bool(options.resume)
        self._cwd = str(pl.Path(options.cwd).expanduser().resolve()) if options.cwd else os.getcwd()
        suffix = self._session_id.replace("-", "")[:12]
        self._tmux_socket = f"ccsdk_{suffix}"
        self._tmux_session = f"cc_{suffix}"
        self._workdir = pl.Path(tempfile.mkdtemp(prefix="cc_sdk_"))
        self._stderr_path = self._workdir / "stderr.log"
        self._sock_path = str(self._workdir / "bridge.sock")
        self._bridge = Bridge(socket_path=self._sock_path, hooks=options.hooks, log=self._log)
        self._transcript_path: pl.Path | None = None
        self._offset = 0
        # Turns are matched to Stop hooks by COUNT, not by a shared event: the Nth Stop
        # completes the Nth turn. A late Stop from an interrupted prior turn then only
        # advances the count toward the current turn's threshold instead of ending it early.
        self._turn_index = 0
        self._stops_received = 0
        self._turn_started = 0.0
        self._interrupt_lock = asyncio.Lock()
        self._last_usage: dict[str, tp.Any] | None = None
        self._exit_code: int | None = None
        self._stderr_read = 0
        self._ready = asyncio.Event()
        self._compaction_started = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None

    # --- public API ---

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def returncode(self) -> int | None:
        return self._exit_code

    def is_alive(self) -> bool | None:
        """Liveness of the underlying claude process, as a tri-state.

        None  — unknown: the session has not been launched yet (no __aenter__).
        True  — launched and still running (no exit code observed).
        False — launched and exited (an exit code was observed).
        """
        if self._monitor_task is None:
            return None
        return self._exit_code is None

    async def __aenter__(self) -> "ClaudeSDKClient":
        try:
            _preseed_config(self._cwd)
            self._register_internal_hooks()
            for server in self._options.mcp_servers.values():
                if isinstance(server, McpServer):
                    self._bridge.register_tools(server.tools)
            await self._bridge.start()
            self._write_config_files()
            await self._launch()
            self._monitor_task = asyncio.create_task(self._monitor())
            await self._await_ready()
        except BaseException:
            # __aexit__ is NOT called when __aenter__ raises, so a failed startup
            # (e.g. resume failure) would otherwise leak the tmux server, the claude
            # process, the bridge socket, the monitor task, and the temp dir — once per
            # resume retry. Tear everything down before propagating.
            await self._cleanup()
            raise
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._cleanup()

    async def _cleanup(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        await tmux.kill_server(self._tmux_socket)
        await self._bridge.stop()
        for child in self._workdir.glob("*"):
            child.unlink(missing_ok=True)
        try:
            self._workdir.rmdir()
        except OSError:
            pass

    def _find_transcript(self) -> pl.Path | None:
        base = pl.Path(os.path.expanduser("~/.claude/projects"))
        matches = sorted(base.glob(f"*/{self._session_id}.jsonl"))
        return matches[0] if matches else None

    async def query(self, prompt: str) -> None:
        if self._transcript_path is None:
            self._transcript_path = self._find_transcript()
        self._offset = self._transcript_path.stat().st_size if self._transcript_path is not None and self._transcript_path.exists() else 0
        self._turn_index += 1
        # Clamp stops_received so it cannot pre-satisfy the new turn's threshold.
        # interrupt() credits stops_received = turn_index, but a late Stop hook can
        # still arrive in the 50-200ms window and push it one higher. Clamping here
        # restores the invariant (stops_received < turn_index) before receive_response()
        # runs, so the new turn always waits for its own Stop rather than being satisfied
        # instantly by an over-credited count from the previous turn.
        self._stops_received = min(self._stops_received, self._turn_index - 1)
        self._turn_started = time.monotonic()
        await tmux.submit_text(self._tmux_socket, self._tmux_session, prompt)

    async def receive_response(self) -> tp.AsyncIterator[tp.Any]:
        if self._transcript_path is None:
            return
        threshold = self._turn_index
        while True:
            for msg in self._drain():
                yield msg
            if self._stops_received >= threshold:
                async for msg in self._post_stop_drain():
                    yield msg
                yield self._make_result()
                return
            if self._exit_code is not None:
                raise ClaudeSDKError(f"claude exited (code {self._exit_code})\n{self._stderr_tail()}")
            await asyncio.sleep(_POLL_S)

    async def interrupt(self) -> None:
        # The lock serialises concurrent callers (monitor-loop vs processor) so the guard
        # and credit are atomic: a second caller sees the updated stops_received after the
        # first credits, rather than both passing the guard and sending four Escapes.
        async with self._interrupt_lock:
            # Skip if the current turn already completed: at idle, Escapes don't interrupt
            # anything and a double-Escape opens the TUI's rewind dialog instead.
            if self._stops_received >= self._turn_index:
                return
            # A single ESC byte never registers: the TUI's escape-sequence parser buffers it
            # waiting for a follow-up byte that never comes (verified against claude v2.1.159,
            # where a lone Escape let generation run to completion). Sending Escape twice
            # flushes the first as a real Escape keypress and reliably interrupts.
            try:
                await tmux.send_double_escape(self._tmux_socket, self._tmux_session)
            finally:
                # Credit in finally so a cancelled send_double_escape still accounts for the
                # abandoned turn and doesn't wedge receive_response until response_timeout.
                # An interrupted turn never fires its Stop hook, so account for the abandoned
                # turn here. Without this, every turn after an interrupt waits for a Stop
                # count that can never be reached and hangs.
                self._stops_received = max(self._stops_received, self._turn_index)

    async def get_context_usage(self) -> dict[str, tp.Any]:
        usage = self._last_usage or {}
        keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "output_tokens")
        total = sum(usage[k] for k in keys if k in usage and isinstance(usage[k], int))
        configured = self._options.max_context_tokens
        if configured:
            # The user pinned a window; report usage against exactly that.
            max_tokens = configured
        else:
            # The caller supplies both windows (no model constants here). Stay on the conservative
            # `context_window` until usage actually exceeds it — which can only happen if the larger
            # `expanded_context_window` is really active (the 1M beta is silently ignored on some
            # auth modes) — so the overflow warning in diagnostics.log_context_usage still fires
            # near the real limit instead of never.
            max_tokens = self._options.context_window or 0
            expanded = self._options.expanded_context_window
            if expanded and max_tokens and total > max_tokens:
                max_tokens = expanded
        percentage = (total / max_tokens * 100) if max_tokens else 0.0
        return {"percentage": percentage, "totalTokens": total, "maxTokens": max_tokens}

    async def snapshot_pane(self) -> str | None:
        """Raw text of the live claude TUI pane, or None if the session isn't running.

        The silence watchdog uses this to surface what a wedged TUI is actually showing
        (a frozen prompt, an unsubmitted paste, a modal) instead of only reporting silence.
        """
        if self._monitor_task is None or self._exit_code is not None:
            return None
        try:
            return await tmux.capture_pane(self._tmux_socket, self._tmux_session)
        except (OSError, RuntimeError):
            return None

    async def compact(self, instructions: str = "") -> None:
        """Compact the conversation in place via `/compact` and wait for it to finish.

        Manual /compact rewrites the SAME session transcript (resume keeps working) and never
        fires a Stop hook, so this does NOT touch the turn/Stop accounting query() relies on.
        It waits for PreCompact (compaction began), then for the isCompactSummary transcript
        line (compaction finished) — not for quiescence, since the summarization request can
        leave the transcript silent for tens of seconds mid-compaction. Both waits are bounded;
        on timeout it logs and returns so a caller that compacts-then-restarts still proceeds."""
        if self._transcript_path is None:
            self._transcript_path = self._find_transcript()
        cursor = self._transcript_path.stat().st_size if self._transcript_path and self._transcript_path.exists() else 0
        command = f"/compact {instructions}".strip()
        self._compaction_started.clear()
        await tmux.submit_text(self._tmux_socket, self._tmux_session, command)
        try:
            await asyncio.wait_for(self._compaction_started.wait(), _COMPACT_START_TIMEOUT_S)
        except TimeoutError:
            self._log("compact: PreCompact never fired — nothing to compact")
            return
        if self._transcript_path is None:
            self._log("compact: no transcript to watch for the summary")
            return
        deadline = time.monotonic() + _COMPACT_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._exit_code is not None:
                raise ClaudeSDKError(f"claude exited during compaction (code {self._exit_code})\n{self._stderr_tail()}")
            objects, cursor = transcript.read_new_objects(self._transcript_path, cursor)
            if any(transcript.is_compact_summary(obj) for obj in objects):
                self._log("compact: summary written")
                return
            await asyncio.sleep(_POLL_S)
        self._log("compact: timed out waiting for the compaction summary")

    # --- internals ---

    def _register_internal_hooks(self) -> None:
        async def on_session_start(payload: dict[str, tp.Any]) -> None:
            if "transcript_path" in payload:
                self._transcript_path = pl.Path(payload["transcript_path"])
            self._ready.set()

        async def on_stop(payload: dict[str, tp.Any]) -> None:
            # Clamp to turn_index: interrupt() already credits stops_received up to turn_index
            # when it fires, so a late Stop that arrives in the 50-200ms window after interrupt()
            # must not increment past the current turn's threshold and pre-satisfy the next turn.
            self._stops_received = min(self._stops_received + 1, self._turn_index)

        async def on_precompact(payload: dict[str, tp.Any]) -> None:
            self._compaction_started.set()

        self._bridge.on("SessionStart", on_session_start)
        self._bridge.on("Stop", on_stop)
        self._bridge.on("PreCompact", on_precompact)

    def _hook_events(self) -> list[str]:
        return sorted({str(e) for e in self._options.hooks}.union(_ALWAYS_EVENTS))

    def _write_config_files(self) -> None:
        sysprompt = self._options.system_prompt or ""
        (self._workdir / "system_prompt.txt").write_text(sysprompt)
        # PYTHONSAFEPATH stops Python from prepending the script's own directory (cc_sdk/) to
        # sys.path. That is the general guard so no cc_sdk module can shadow a stdlib module for
        # these stdlib-only helpers when claude runs them by path (cc_sdk/types.py would otherwise
        # shadow stdlib `types`). The agent process is unaffected — it imports cc_sdk as a package.
        # test_cc_sdk.py asserts this guard is always emitted and that the helpers import cleanly.
        py = shlex.quote(sys.executable)
        hooks: dict[str, tp.Any] = {}
        for event in self._hook_events():
            command = f"PYTHONSAFEPATH=1 {py} {shlex.quote(str(_FORWARD))} {shlex.quote(event)} {shlex.quote(self._sock_path)}"
            hooks[event] = [{"matcher": "*", "hooks": [{"type": "command", "command": command}]}]
        # skipDangerousModePermissionPrompt suppresses the one-time "Bypass Permissions mode"
        # acceptance dialog that interactive Claude Code shows on first use — without it the TUI
        # blocks at that prompt forever and SessionStart never fires. (The headless SDK never hit
        # this because dialogs are interactive-only.)
        settings = {"skipDangerousModePermissionPrompt": True, "hooks": hooks}
        (self._workdir / "settings.json").write_text(json.dumps(settings))
        if self._bridge.tools:
            mcp = {
                "mcpServers": {
                    name: {
                        "type": "stdio",
                        "command": sys.executable,
                        "args": [str(_MCP_STDIO), self._sock_path],
                        "env": {"PYTHONSAFEPATH": "1"},
                        # Load this server's tools upfront instead of behind ToolSearch (>= 2.1.121),
                        # so the agent's few control tools (mark_setup_done, ...) are always present
                        # during first-start rather than something the model has to go search for.
                        "alwaysLoad": True,
                    }
                    for name, server in self._options.mcp_servers.items()
                    if isinstance(server, McpServer)
                }
            }
            (self._workdir / "mcp.json").write_text(json.dumps(mcp))

    async def _launch(self) -> None:
        # tmux is a hard dependency: the session runs the claude TUI inside a private tmux
        # server. Fail loudly with the fix instead of a bare FileNotFoundError raised deep in
        # tmux.py when the binary is missing (e.g. a container rebuilt from a pre-tmux snapshot).
        if shutil.which("tmux") is None:
            raise RuntimeError("cc_sdk requires tmux on $PATH; install it (e.g. `apt-get install -y tmux`)")
        sysprompt_file = self._workdir / "system_prompt.txt"
        settings_file = self._workdir / "settings.json"
        mcp_file = self._workdir / "mcp.json" if self._bridge.tools else None
        # Resolve the pinned claude binary cc_sdk owns (downloads+verifies on first use).
        # Off-loop: the first fetch does blocking network I/O.
        claude_bin = await asyncio.get_running_loop().run_in_executor(None, ensure_claude)
        args = _claude_args(
            self._options,
            claude_bin=claude_bin,
            session_id=self._session_id,
            resuming=self._resuming,
            sysprompt_file=sysprompt_file,
            settings_file=settings_file,
            mcp_file=mcp_file,
        )
        # IS_SANDBOX=1 is required for bypassPermissions to work when the agent runs as root
        # (the default in the container) — Claude Code otherwise refuses skip/bypass permissions
        # under root for safety. The agent's container is exactly that isolated sandbox.
        # DISABLE_AUTOUPDATER keeps the pinned binary fixed: the launcher would otherwise
        # update itself at runtime and drift away from the version cc_sdk vendored.
        env = {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "IS_SANDBOX": "1",
            "DISABLE_AUTOUPDATER": "1",
        }
        env.update(_thinking_env(self._options))
        env.update(self._options.env)
        env_prefix = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        claude_cmd = " ".join(shlex.quote(a) for a in args)
        stderr = shlex.quote(str(self._stderr_path))
        inner = f"{env_prefix} {claude_cmd} 2>{stderr}; printf '{_EXIT_MARKER}%s\\n' \"$?\" >>{stderr}; exec sleep 2147483647"
        await tmux.start_session(self._tmux_socket, self._tmux_session, cwd=self._cwd, command=inner)

    async def _await_ready(self) -> None:
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._ready.is_set():
                return
            if self._exit_code is not None:
                raise ClaudeSDKError(f"claude exited during startup (code {self._exit_code})\n{self._stderr_tail()}")
            await asyncio.sleep(_POLL_S)
        raise ClaudeSDKError(f"timed out waiting for claude session start\n{self._stderr_tail()}")

    def _drain(self) -> list[tp.Any]:
        if self._transcript_path is None:
            return []
        objects, self._offset = transcript.read_new_objects(self._transcript_path, self._offset)
        messages: list[tp.Any] = []
        for obj in objects:
            usage = transcript.usage_from(obj)
            if usage is not None:
                self._last_usage = usage
            msg = transcript.assistant_message_from(obj)
            if msg is not None:
                messages.append(msg)
        return messages

    async def _post_stop_drain(self) -> tp.AsyncIterator[tp.Any]:
        """After Stop fires, give the transcript a moment to flush the final line(s)."""
        deadline = time.monotonic() + _POST_STOP_DRAIN_S
        empties = 0
        while time.monotonic() < deadline and empties < 2:
            messages = self._drain()
            if messages:
                empties = 0
                for msg in messages:
                    yield msg
            else:
                empties += 1
            await asyncio.sleep(0.1)

    def _make_result(self) -> ResultMessage:
        duration_ms = (time.monotonic() - self._turn_started) * 1000 if self._turn_started else None
        return ResultMessage(
            session_id=self._session_id,
            usage=self._last_usage,
            total_cost_usd=None,
            duration_ms=duration_ms,
        )

    async def _monitor(self) -> None:
        while True:
            self._read_stderr()
            await asyncio.sleep(0.25)

    def _read_stderr(self) -> None:
        if not self._stderr_path.exists():
            return
        with self._stderr_path.open("r", errors="replace") as f:
            f.seek(self._stderr_read)
            chunk = f.read()
            self._stderr_read = f.tell()
        if not chunk:
            return
        for line in chunk.splitlines():
            if line.startswith(_EXIT_MARKER):
                try:
                    self._exit_code = int(line[len(_EXIT_MARKER) :].strip())
                except ValueError:
                    self._exit_code = -1
                continue
            if self._options.stderr is not None:
                self._options.stderr(line)

    def _stderr_tail(self) -> str:
        if not self._stderr_path.exists():
            return "(no stderr)"
        lines = [line for line in self._stderr_path.read_text(errors="replace").splitlines() if not line.startswith(_EXIT_MARKER)]
        return "\n".join(lines[-20:])

    def _log(self, message: str) -> None:
        if self._options.stderr is not None:
            self._options.stderr(f"[cc_sdk] {message}")
