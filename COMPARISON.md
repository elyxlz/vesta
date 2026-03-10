# Vesta vs. NanoClaw vs. OpenClaw vs. SimpleClaw vs. Hermes Agent

## Executive Summary

All five projects share the same goal: a **persistent, autonomous personal AI assistant** that monitors notifications, handles tasks, and connects to messaging platforms. They diverge significantly in architecture, philosophy, and complexity.

| | **Vesta** | **NanoClaw** | **OpenClaw** | **SimpleClaw** | **Hermes Agent** |
|---|---|---|---|---|---|
| **Author** | elyxlz | Gavriel Cohen | Peter Steinberger | Savio Martin | Nous Research |
| **License** | MIT | MIT | MIT | Apache 2.0 | MIT |
| **GitHub Stars** | — | ~20K | ~247K | ~minimal | ~growing |
| **Primary Language** | Python + Rust | TypeScript | TypeScript | N/A (wrapper) | Python |
| **Codebase Size** | ~2K LOC agent | ~4K LOC core | ~400K LOC | N/A | ~15K+ LOC |
| **LLM Backend** | Claude (Agent SDK) | Claude (Agent SDK) | Model-agnostic | OpenClaw's | Model-agnostic |
| **Deployment** | Docker container | Docker/Apple Containers | Daemon (launchd/systemd) | Hosted SaaS | Docker/SSH/Modal/Daytona |

---

## 1. Architecture

### Vesta
- **Three-layer architecture**: Rust CLI on host → Docker container → Python agent inside.
- The CLI (`cli/src/`) manages the container lifecycle: `setup`, `start`, `stop`, `attach`, `shell`, `backup`, `destroy`, `rebuild`. Platform-specific modules for Linux (direct Docker), macOS (vfkit VM), and Windows (WSL2).
- Inside the container, the Python agent runs as a single async process with three concurrent tasks:
  1. **Input handler** — reads stdin (console mode)
  2. **Message processor** — sequential message queue consuming via the Claude Agent SDK
  3. **Monitor loop** — polls for notifications, runs proactive checks, triggers the nightly "dreamer"
- **WebSocket server** (aiohttp on port 7865) enables the Tauri+Svelte desktop app to connect.
- **Event bus** (pub/sub) decouples UI updates from agent logic.
- Clean separation: the agent never touches Docker; the CLI never touches the LLM.

### NanoClaw
- **Single Node.js process** as orchestrator. Channels self-register at startup based on which credentials are present.
- **Container-per-agent model**: every chat group/swarm member runs in its own isolated Linux container (Docker on Linux, Apple Containers on macOS, WSL2+Docker on Windows).
- Data flows: messaging app → SQLite queue → polling loop → container agent → response. IPC via filesystem.
- ~15 source files, ~35K tokens total. Radically minimal.

### OpenClaw
- **Hub-and-spoke / control-plane**: a central Gateway (WebSocket server on port 18789) coordinates all channels, agents, CLI clients, web UIs, and device nodes.
- **pnpm monorepo**: packages for core, gateway, agent, CLI, SDK, UI.
- Supports 22+ messaging channels, device nodes (macOS, iOS, Android), and a "Live Canvas" agent-driven UI.
- The most complex architecture of the five — ~400K LOC with 53 config files and 70+ dependencies.

### SimpleClaw
- **Not an agent framework** — it's a managed deployment wrapper around OpenClaw. Provisions cloud VMs with pre-configured OpenClaw instances.
- The GitHub repo contains 4 files (assets, .gitignore, LICENSE, README.md). The actual logic lives in the hosted service.
- Users select a model, a messaging channel, and click launch. ~1 minute to a running OpenClaw instance.

### Hermes Agent
- **ReAct loop** (Observe → Reason → Act) with max 60 iterations per turn.
- Core `AIAgent` class maintains conversation state, executes tool calls, manages context compression.
- Six terminal backends: Local, Docker, SSH, Daytona, Singularity, Modal.
- Gateway process handles multi-platform messaging (Telegram, Discord, Slack, WhatsApp, Signal, CLI).
- Fresh agent per gateway message (keyed by `{platform}:{user_id}:{chat_id}`), persistent in CLI mode.

---

## 2. LLM Integration

### Vesta
- **Claude-only** via the Claude Agent SDK (`claude-agent-sdk` Python package).
- Uses `ClaudeSDKClient` with `ClaudeAgentOptions` — system prompt injection, hook-based tool logging, permission bypass mode.
- Session resumption via persisted `session_id` — the SDK maintains conversation continuity across restarts.
- Extended thinking enabled (`max_thinking_tokens=10000`).
- MCP server integration for custom tools (e.g., `restart_vesta` tool).

### NanoClaw
- **Claude-only** — runs Claude Code inside containers via the Claude Agent SDK.
- Agents inherit Claude Code's full capabilities: shell, file I/O, web search, web browsing (Chromium), agent delegation.

### OpenClaw
- **Model-agnostic**: Anthropic, OpenAI, Google, or local models via Ollama/LM Studio/any OpenAI-compatible server.
- Supports model failover chains and auth profile rotation.
- No extended thinking — relies on tool-use patterns instead.

### SimpleClaw
- Inherits OpenClaw's model support. Offers Claude Opus 4.5, GPT-5.2, Gemini 3 Flash at setup time.

### Hermes Agent
- **Model-agnostic**: supports any OpenAI-compatible API (Nous Portal, OpenRouter 200+ models, OpenAI, Ollama, vLLM, llama.cpp, etc.).
- Ships with **Hermes-3** (Llama 3.1-based, RL-trained via Atropos) optimized for tool-calling accuracy.
- Can switch models with `hermes model` CLI command.

---

## 3. Memory & Context Management

### Vesta
- **File-based memory**: `MEMORY.md` is the main system prompt / persistent memory file, injected at session start.
- **Skills as memory**: each skill has a `SKILL.md` that becomes part of the agent's knowledge.
- **Nightly "dreamer"**: at a configurable hour (default 4 AM), the agent runs a special prompt to review conversations, consolidate learnings, and write reflections to `dreamer/YYYY-MM-DD.md`. The conversation is then archived and session resets.
- **Session persistence**: `session_id` file allows conversation resumption across agent restarts (via Claude SDK's resume feature).
- **Prompt templates**: `prompts/` directory with named templates (`first_start.md`, `restart.md`, `dreamer.md`, `proactive_check.md`, `notification_suffix.md`).
- **Conversation archiving**: JSONL transcripts archived to `conversations/`.
- No vector store, no embeddings, no semantic search. Memory is the system prompt + file system.

### NanoClaw
- **Per-group `CLAUDE.md`**: each chat group gets its own persistent memory file.
- **SQLite**: structured message storage with per-group queuing and concurrency control.
- **Isolation**: memory is strictly per-group — no cross-contamination.
- No semantic search or embeddings.

### OpenClaw
- **The most sophisticated memory system** of all five:
  - `SOUL.md` — persona (always injected)
  - `AGENTS.md` — operating instructions (always injected)
  - `MEMORY.md` — curated long-term facts (private sessions only)
  - `memory/YYYY-MM-DD.md` — daily append-only logs
- **Hybrid retrieval**: vector similarity (cosine) + BM25 keyword relevance with weighted score fusion. MMR re-ranking for diversity. Temporal decay (30-day half-life).
- **Embedding storage**: per-agent SQLite with `sqlite-vec`. Auto-selects embedding provider (local GGUF > OpenAI > Gemini > Voyage > Mistral).
- **Pre-compaction memory flush**: silent agentic turn saves important context to disk before context window truncation. "Virtual memory for cognition."

### SimpleClaw
- Inherits OpenClaw's memory system. Deploys blank instances with no pre-built templates.

### Hermes Agent
- **Multi-level memory**:
  - Session memory (conversation context)
  - `MEMORY.md` — agent's curated notes
  - `USER.md` — user profile via Honcho dialectic modeling
- Memory is **snapshot-frozen at session start** — mid-session writes update disk but don't affect the current prompt (prevents feedback loops).
- **SQLite FTS5** for cross-session recall with LLM summarization.
- **Context compression** at ~85% of context window: semantic chunking by tool boundaries, auxiliary LLM summarization, protects first/last N messages.
- **Self-improving skills**: the agent autonomously creates, stores, and improves procedural knowledge over time.

---

## 4. Tools & Skills

### Vesta
- **Independent CLI tools** — each is its own project with separate dependencies:
  - `browser/` — TypeScript, CDP-based browser automation (navigation, screenshots, interaction, keyboard, PDF capture)
  - `google/` — Python, Google Calendar/Gmail/Meet integration with OAuth
  - `microsoft/` — Python, Microsoft Graph API (email, calendar) with OAuth
  - `whatsapp/` — Go, WhatsApp messaging bridge
  - `reminder/` — Python, scheduled reminders with SQLite backend
  - `tasks/` — Python, task management with notifications
  - `zoom/` — Python, Zoom integration
- **"Never share code between CLIs"** — strict isolation prevents coupling.
- **Skills** are `SKILL.md` + optional `SETUP.md` + scripts. Templates in `agent/src/vesta/templates/skills/` are copied to `agent/memory/skills/` at init. Symlinked into `.claude/skills/` for the SDK.
- Skills include: browser, google, microsoft, keeper, onedrive, reminders, tasks, whatsapp, whisper, zoom, upstream (PR automation), what-day.
- **MCP tool**: `restart_vesta` — allows the agent to restart itself to reload memory/skills.
- No MCP servers beyond built-in. Tools are CLI executables the agent invokes via shell.

### NanoClaw
- Tools come from **Claude Code running inside containers**: shell, file I/O, web search, web browsing, agent delegation (swarms).
- Host process provides: scheduled tasks (cron), persistent memory (SQLite), messaging.
- **Skills-over-features contribution model**: contributors submit Claude Code skills that transform individual forks rather than PRing to the main codebase.

### OpenClaw
- **Tools are capabilities** ("organs"): `read`, `write`, `exec`, `web_search`, `web_fetch`, `browser` (CDP).
- **Skills are instructions** ("textbooks"): a folder with `SKILL.md` (YAML frontmatter + Markdown). No SDK, no compilation.
- **ClawHub**: public skill registry with 13,700+ community-built skills. Semver versioning, VirusTotal scanning, vector-based search.
- Skill precedence: workspace > managed > bundled. Auto-activation if corresponding CLI tool detected.
- MCP server support via JSON-RPC 2.0 over stdio or HTTP.

### SimpleClaw
- Inherits OpenClaw's tools and skills. No custom additions.

### Hermes Agent
- **40+ built-in tools** across categories: web (search, browser), system (terminal, filesystem), AI (vision, image gen, TTS, multi-model reasoning), planning (task planning, cron, memory).
- **Self-registration pattern**: each tool module defines schema + handler + availability check, calls `registry.register()`. Discovery via `_discover_tools()`.
- **40+ bundled skills** (MLOps, GitHub, diagramming, etc.) using the `agentskills.io` open standard.
- **Subagent delegation**: spawn isolated child agents with restricted toolsets (recursion depth limit of 2).
- MCP server support for extended capabilities.

---

## 5. Messaging & Notifications

### Vesta
- **Notification-driven architecture**: tools write JSON files to `~/notifications/`. The monitor loop polls every 2 seconds, buffers notifications for 3 seconds, then batches them into the agent's message queue.
- **WhatsApp** via a Go bridge that writes notification files.
- **Google/Microsoft** tools have built-in notification monitors for email/calendar.
- No native Telegram/Discord/Slack/Signal integration — relies on tool CLIs to bridge.
- **Proactive checks**: configurable interval (default 60 min) — agent runs a periodic self-check prompt.

### NanoClaw
- **Multi-channel native**: WhatsApp, Telegram, Slack, Discord, Gmail, Signal.
- Channels self-register based on credentials present at startup.
- SQLite-backed message queuing with per-group concurrency control.

### OpenClaw
- **22+ channels**: WhatsApp (Baileys), Telegram (grammy), Slack (Bolt), Discord (discord.js), Signal, iMessage (BlueBubbles), IRC, Teams, Matrix, Google Chat, LINE, Mattermost, Nostr, and more.
- **Proactive heartbeat**: configurable periodic check (default 30 min) via `HEARTBEAT.md`.
- **Voice wake + talk mode**: always-on listening with wake words.
- **Device nodes**: macOS/iOS/Android can pair for local action execution.

### SimpleClaw
- Telegram and Discord native. WhatsApp planned. Inherits OpenClaw's channel support.

### Hermes Agent
- **Multi-channel gateway**: Telegram, Discord, Slack, WhatsApp, Signal, CLI.
- Voice memo transcription with cross-platform conversation continuity.
- Cron scheduling for autonomous behavior.

---

## 6. Security & Isolation

### Vesta
- **Docker container isolation**: the agent runs entirely inside a container. The Rust CLI manages the container boundary.
- `permission_mode="bypassPermissions"` — the agent has unrestricted tool access inside its sandbox.
- No encryption of memory files. State is on the container's filesystem.
- Platform-aware: Linux direct Docker, macOS behind vfkit VM (additional isolation layer), Windows behind WSL2.

### NanoClaw
- **OS-level container isolation by default**: every agent runs in its own Linux container with filesystem isolation enforced by the kernel.
- Secrets passed via stdin JSON, never in `process.env`.
- Mount allowlists with symlink escape detection.
- Containers run as non-root with read-only project mounts.
- **Strongest security posture** of the five — container isolation is architectural, not optional.

### OpenClaw
- **Application-level permission model**: tools are enabled/disabled per configuration.
- No container isolation by default (available but not required).
- Plain-text memory files fully exposed if host is compromised.
- **Security concerns raised by CrowdStrike and Cisco**: misconfigured instances as "AI backdoor agents," third-party skill data exfiltration.
- Not considered enterprise-ready.

### SimpleClaw
- Inherits OpenClaw's security model.
- Additional risk: API keys managed through a third-party service.

### Hermes Agent
- **Six terminal backends** with varying isolation: Local (least), Docker (container), SSH (remote), Daytona (remote sandboxed), Singularity (HPC), Modal (serverless).
- Docker mode: read-only root, dropped capabilities, PID limits, namespace isolation.
- Skill quarantine system: new agent-created skills are sandboxed until reviewed.

---

## 7. Autonomy & Self-Improvement

### Vesta
- **Nightly dreamer**: at a configurable hour, the agent consolidates the day's learnings, archives the conversation, writes a dreamer summary, and resets the session. This is the primary self-improvement mechanism.
- **Proactive checks**: periodic prompts to review tasks, calendars, notifications.
- **Self-restart**: the agent can trigger its own restart to reload memory/skills via the `restart_vesta` MCP tool.
- No automatic skill creation — skills are authored by developers and placed in the skills directory.

### NanoClaw
- **Agent swarms**: teams of specialized agents collaborating on complex tasks. First personal AI assistant to support this.
- No explicit self-improvement loop — relies on Claude Code's inherent capabilities.

### OpenClaw
- **Proactive heartbeat**: periodic `HEARTBEAT.md` check with configurable interval.
- **Pre-compaction memory flush**: automatic context preservation before window truncation.
- No automatic skill creation, but the low barrier to manual skill creation (just Markdown) enables rapid iteration.

### SimpleClaw
- Inherits OpenClaw's autonomy features.

### Hermes Agent
- **Strongest self-improvement story**: the agent autonomously creates skills from experience, improves them during use, and persists procedural knowledge across sessions.
- **Nudge interval**: periodically reminds the agent to update memory.
- **Training data pipeline**: can generate thousands of tool-calling trajectories for fine-tuning models — the agent improves the model that runs the agent.
- **Subagent delegation**: parallel workstreams with isolated contexts.

---

## 8. Desktop/UI Experience

### Vesta
- **Tauri + Svelte desktop app** (`app/`): native cross-platform app that connects to the agent via WebSocket.
- Event history replay on connect — the app shows the full conversation history.
- Real-time state indicators: idle, thinking, tool_use.
- Interrupt support from the UI.

### NanoClaw
- No dedicated UI — interaction through messaging apps.

### OpenClaw
- **CLI** as primary interface, plus a **web UI**.
- **Live Canvas (A2UI)**: agent-driven visual workspace.
- 22+ messaging channels as alternative UIs.

### SimpleClaw
- Web dashboard for deployment management. Agent interaction through messaging apps.

### Hermes Agent
- CLI as primary interface. Gateway for messaging platform interaction.
- No dedicated desktop app.

---

## 9. Deployment Complexity

### Vesta
- **Moderate**: `vesta setup` handles container creation, image pull/build, and auth. One command to get running.
- Requires Docker. macOS needs vfkit VM setup. Windows needs WSL2.
- Backup/restore via `vesta backup` and `vesta rebuild`.

### NanoClaw
- **Low**: `npm install && npm run build && npm start`. Claude-assisted setup.
- Light enough for a Raspberry Pi.
- Service management via launchd (macOS) or systemd (Linux).

### OpenClaw
- **High**: ~30-60 minutes manual setup. 53 config files, 70+ dependencies.
- `npm install -g openclaw@latest` for basic install, but configuration is complex.
- Multiple deployment options: local daemon, Docker, Nix, VPS with Tailscale, Cloudflare Workers.

### SimpleClaw
- **Lowest**: ~1 minute. Web dashboard, click to deploy.
- $44/month average. BYOK for LLM API costs.

### Hermes Agent
- **Low-moderate**: single curl command handles everything.
- Serverless options (Daytona, Modal) offer near-zero-cost hibernation.
- Runs on a $5 VPS up to GPU clusters.

---

## 10. Philosophy & Positioning

| | **Philosophy** | **Target User** |
|---|---|---|
| **Vesta** | Opinionated, integrated, Claude-native. One agent per person, running 24/7 in a Docker sandbox. Rust CLI for robustness, Python for agent flexibility. | Developer building a personal AI assistant with deep integrations (Google, Microsoft, WhatsApp). |
| **NanoClaw** | Radical minimalism. Fork it, own it, audit it. Container isolation is non-negotiable. Skills over features. | Privacy-conscious developer who wants full auditability and control. |
| **OpenClaw** | Kitchen-sink feature maximalism. Support everything, connect everything. Scale through community (13K+ skills). | Broad audience — from hobbyists to power users — who want maximum channel coverage and ecosystem. |
| **SimpleClaw** | Remove the friction. OpenClaw in one click. | Non-technical users who want a personal AI assistant without DevOps knowledge. |
| **Hermes Agent** | Self-improving AI that gets better over time. Training data flywheel. Open research platform. | AI researchers and power users who want an agent that learns and improves its own model. |

---

## 11. Key Differentiators Summary

### Vesta's Unique Strengths
1. **Rust CLI + Python agent split** — systems-level container management with high-level agent logic
2. **Nightly dreamer** — structured daily reflection and memory consolidation
3. **Native desktop app** (Tauri + Svelte) with real-time WebSocket updates
4. **Polyglot tool ecosystem** — Go (WhatsApp), TypeScript (browser), Python (Google/Microsoft/tasks/reminders)
5. **Session resumption** — conversations survive restarts via Claude SDK's session persistence
6. **Clean notification pipeline** — JSON file-based, tool-agnostic, buffered batch processing

### Where Vesta Could Learn from Others
1. **From NanoClaw**: Per-group memory isolation, agent swarms, more aggressive container security (non-root, read-only mounts)
2. **From OpenClaw**: Semantic memory search (vector + BM25 hybrid retrieval), pre-compaction memory flush, larger channel ecosystem, a skill marketplace
3. **From Hermes Agent**: Automatic skill creation from experience, context compression with semantic chunking, cross-session FTS recall, model-agnostic support, subagent delegation with depth limits
4. **From all**: More messaging channel integrations (Telegram, Discord, Slack, Signal natively rather than via tools)
