# cc_sdk

A drop-in replacement for the public surface of the official `claude_agent_sdk`,
implemented by driving the **interactive `claude` CLI** inside tmux rather than the
headless control protocol. The rest of the agent (`core/`) imports `cc_sdk` exactly
as it imported `claude_agent_sdk` before: same message/block types, same hook
plumbing, same MCP-tool registration, same `ClaudeSDKClient` lifecycle.

## How it works

```
              ┌─────────────────────── agent process ───────────────────────┐
              │  ClaudeSDKClient                                             │
  query() ───▶│   tmux paste + Enter ──────────────┐                        │
              │                                     ▼                        │
              │                          ┌──────────────────┐               │
              │  receive_response()  ◀── │  tmux: claude TUI │  (own -L srv) │
              │   tail transcript.jsonl  └──────────────────┘               │
              │            ▲                    │  hooks │  mcp stdio        │
              │            │                    ▼        ▼                   │
              │        ~/.claude/projects   _forward.py  _mcp_stdio.py       │
              │                                 │            │               │
              │                                 ▼            ▼               │
              │                          ┌──────────────────────┐           │
              │   hook callbacks  ◀───── │  bridge (unix socket) │ ──▶ tools │
              │   (PreToolUse, …)        └──────────────────────┘  handlers │
              └─────────────────────────────────────────────────────────────┘
```

- **Prompts** are submitted by bracketed-pasting the text into the tmux pane and
  sending `Enter` (multi-line stays in the box; a single Enter submits; leading `/`
  runs as a slash command). **Interrupt** sends a double `Escape`: the TUI's
  escape-sequence parser buffers a lone ESC waiting for a follow-up byte that never
  comes (verified against claude v2.1.159), so a second ESC is needed to flush the
  first as a real keypress. An interrupted turn never fires its `Stop` hook (no late
  Stop arrives either), so `interrupt()` credits the abandoned turn's Stop itself —
  otherwise every later turn would wait for a Stop count it can never reach.
- **Responses** are read by tailing the session transcript JSONL
  (`~/.claude/projects/<munged-cwd>/<session-id>.jsonl`); each main-agent `assistant`
  line becomes an `AssistantMessage` with the same block types as the SDK. A turn
  ends on the native `Stop` hook, after which a synthetic `ResultMessage` (session id
  + usage) is yielded. Subagent (`isSidechain`) lines are skipped — they surface via
  SubagentStart/Stop hooks instead.
- **Hooks** are configured as native command hooks (`--settings`) that run
  `_forward.py`, which relays the event JSON to the in-process **bridge** over a unix
  socket. The bridge dispatches to the registered `HookMatcher` callbacks, so
  `core.sdk_parsing.make_hooks` works unchanged.
- **MCP tools** registered via `create_sdk_mcp_server` are exposed to `claude` as a
  real stdio MCP server (`_mcp_stdio.py`, wired with `--mcp-config`). The proxy
  forwards `tools/list` / `tools/call` to the bridge, so handlers run in the agent
  process and can mutate live `State`.
- **Startup** pre-seeds `~/.claude.json` (onboarding + per-project trust) so a fresh
  container goes straight to the input box, launches `claude` with
  `--permission-mode bypassPermissions`, and waits for the `SessionStart` hook (which
  also hands us the transcript path).

## Notes

- `_forward.py` and `_mcp_stdio.py` are **stdlib-only** and are launched with
  `PYTHONSAFEPATH=1` so Python does not prepend their directory to `sys.path` — that
  would let `cc_sdk/types.py` shadow the stdlib `types` module and break them.
- Requires `tmux` and the `claude` CLI on `PATH` (both installed in the agent image).
- Running as root (the container default) needs `IS_SANDBOX=1` plus
  `skipDangerousModePermissionPrompt` in `--settings`, or interactive claude blocks on
  permission dialogs before `SessionStart` ever fires. Both are set automatically.

## System prompt semantics

`--system-prompt-file` replaces the entire ~27KB default Claude Code instruction body
with `options.system_prompt` (verified by capturing the actual API request). The only
remnant is a hardcoded one-line identity preamble that cannot be removed by any flag:

- interactive (this SDK): `"You are Claude Code, Anthropic's official CLI for Claude."`
- headless `--print` (the official SDK): `"You are a Claude agent, built on Anthropic's
  Claude Agent SDK."`

i.e. the official SDK never removed that line either — it just words it differently.
The one mode that drops it (`--bare`) also disables hooks and OAuth auth, so it is not
usable here.
