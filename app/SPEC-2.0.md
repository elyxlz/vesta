# Vesta Desktop App — Spec Sheet

## Overview

Vesta is a Tauri + Svelte desktop app for managing personal AI agents that run as Docker containers via the `vestad` daemon. The app provides agent lifecycle management, real-time chat, log streaming, and Claude authentication — all through a minimal, orb-centric UI.

**Tech stack:** Tauri v2 (Rust backend) + Svelte 5 (runes mode) + TypeScript. Communication with vestad via HTTP REST + WebSocket + SSE. No router library — view state managed in `App.svelte`.

**Platforms:** macOS, Windows, Linux. Platform-specific window chrome and setup flows.

---

## Architecture

```
┌────────────────────────────────────┐
│  Tauri Webview (Svelte frontend)   │
│  HTTP/WS/SSE ──────────────────────┼──► vestad daemon (host)
│  Tauri invoke ─────────────────────┼──► Rust backend (platform ops only)
└────────────────────────────────────┘
```

- All agent CRUD, chat, logs, and auth go over **HTTP/WS/SSE** to vestad.
- Only platform setup (`auto_setup`, `platform_check`, `platform_setup`), server connection (`connect_to_server`), and Linux updates (`run_install_script`) use **Tauri invoke**.
- Connection config (URL + API key) persisted in `localStorage` key `vesta-connection`.

---

## Views & Navigation

```
              ┌──────────┐
              │ loading   │
              └────┬─────┘
                   │
                   ▼
          check saved creds
          (localStorage)
           ╱            ╲
      found              not found
         │                   │
         ▼                   ▼
   try GET /health      ┌─────────┐
         │               │ connect  │
    ╱         ╲          └────┬────┘
 success     fail             │ success
    │          │              │
    │          ▼              │
    │     ┌─────────┐        │
    │     │ connect  │        │
    │     └────┬────┘        │
    │          │ success      │
    ▼          ▼              ▼
          ┌──────────┐
          │   home    │ ◄─── always lands here after connection
          └────┬─────┘
               │
               ├──► agent-detail (selected agent)
               │       ├──► agent-chat (overlay)
               │       └──► agent-console (overlay)
               │
               └──► create-agent (inline flow on home)
```

**View type:** `loading` | `connect` | `home` | `agent-detail` | `agent-chat` | `agent-console`

**Transitions:** 150ms opacity fade between views. Chat and Console render as absolute overlays on top of the always-mounted AgentDetail.

---

## Startup Flow (Detail)

1. **`loading`** — Show logo + "loading..." while `autoSetup()` runs (Tauri) and window scales to monitor.
2. **Check saved credentials** — Read `vesta-connection` from `localStorage`. If `url` and `apiKey` exist, attempt `GET /health` with the stored auth header.
3. **Credentials valid** — Connection confirmed. Set `connected = true`, navigate to `home`.
4. **Credentials missing or invalid** — Navigate to `connect`. On invalid creds, clear the stale entry from localStorage.
5. **`connect` → success** — Save creds to localStorage, navigate to `home`.
6. **`home`** — Fetch agent list. Render the home page (agents + create affordance).

---

## Window Shell (`App.svelte`)

### Titlebar
| Element | Behavior |
|---------|----------|
| **Drag region** | Entire titlebar is draggable (Tauri `startDragging`). Excludes `.window-controls`. |
| **Connection indicator** | Green dot + hostname (extracted from URL). Only shown when connected. |
| **Disconnect button** | Logout icon. Tooltip: "disconnect". Clears localStorage connection, returns to `connect` view. |
| **Minimize** (non-macOS) | Platform-specific button. Linux: rounded icon. Windows: caption-style 46×40px. |
| **Close** (non-macOS) | Platform-specific. Linux: rounded, red on hover. Windows: caption-style, `#c42b1c` on hover. |
| macOS | Titlebar padded 78px left for native traffic lights. No custom minimize/close buttons. Close hides window; reopen shows/focuses. |

### Update Bar
- Shown only on `home` or `agent-detail` views, Tauri only.
- **Linux:** Checks GitHub API for latest release. Shows pill: `v{version} available —` **[install]** **[dismiss]**.
- **macOS/Windows:** Uses Tauri updater plugin. Auto-downloads, shows: `v{version} installed — restart to apply` **[dismiss]**.
- Linux install runs `run_install_script` (downloads `.deb`/`.rpm`, uses `pkexec` for elevation).

### Global Tooltip
- Follows pointer position. Any element with `data-tip="text"` shows tooltip on hover.
- Positioned above cursor with clamped bounds. 150ms fade transition.

### Theme
- Light background: `rgba(248, 246, 243, 0.96)`.
- Dark mode: follows `prefers-color-scheme: dark`. Chat/Console views force dark via `.dark` class on window.
- Squircle border radius (`corner-shape: squircle`) on all rounded elements.

---

## Connect (`Connect.svelte`)

Shown when no saved credentials exist, or when saved credentials fail validation.

| Element | Detail |
|---------|--------|
| Heading | "connect" |
| Subtext | "connect to a remote vesta server." |
| Input 1 | `placeholder="host:port"`, autofocus |
| Input 2 | `type="password"`, `placeholder="API key"` |
| **[connect]** | Primary. Disabled if either field empty or busy. Calls `GET /health` to validate, saves connection to localStorage. On success → `home`. |
| Error | Red text below inputs. "could not reach server" or raw error. Optional **[show details]** / **[hide details]**. |

No back button — this is the entry point when unauthenticated.

---

## Home (`Home.svelte`)

The central hub. Always shown after successful connection.

### Layout

Two states based on whether agents exist:

#### When agents exist
- Agent grid at top. Responsive layout: 1 agent → 1 column (centered), 2 → 2 columns (centered), 3+ → 3 columns.
- **[+] New agent** button in top-right corner. Tooltip: "new agent".
- Clicking [+] opens the **create agent** inline flow (see below) — either a modal/panel over the grid or replaces the grid content.
- Clicking an agent card → navigates to `agent-detail`.

#### When no agents exist
- Centered create-agent UI shown directly (no grid, no [+] button needed).
- The home page IS the create flow when empty.

### Agent Card
- Mini orb (animated, color-coded by state) + agent name below.
- Click → navigates to `agent-detail`.
- Orb states: `alive` (green, floating), `active` (amber, faster), `booting` (lighter green), `auth` (blue), `dead` (gray, no animation).

### Per-Card Context Menu (⋮)
Appears on card hover. Click opens dropdown. Close on outside click or Escape.

| Condition | Menu Items |
|-----------|------------|
| Confirming delete | **[confirm delete]** (red) / **[cancel]** (muted) |
| Agent alive | **[chat]** / **[console]** |
| Always | **[start]** or **[stop]** (toggles) |
| Running | **[restart]** |
| Always | **[backup]** / **[load backup]** |
| Divider | — |
| Always | **[delete]** (red, two-step confirm) |

All items disabled when any agent has a busy operation.

### Create Agent Flow (Inline)

Triggered by [+] button (when agents exist) or shown directly (when no agents). Steps:

#### Step: `name`
| Element | Detail |
|---------|--------|
| Heading | "new agent" |
| Subtext | "give it a name to get started." |
| Input | `placeholder="name your agent"`, autofocus, centered text |
| Name normalization | Lowercase, trim, spaces→hyphens, strip non-alphanumeric, collapse hyphens |
| **[create]** | Primary button. Disabled if no normalized name or busy. |
| **[restore from backup]** | Secondary link. Opens hidden file input (`.tar.gz,.gz`). |
| **[cancel]** | Only shown when agents already exist (returns to grid). Hidden when this is the empty-state create. |

#### Step: `creating`
| Element | Detail |
|---------|--------|
| Heading | "setting up" |
| Subtext | "this may take a couple of mins." |
| ProgressBar | Indeterminate. |
| Rotating messages | Cycle every 3s: "setting things up...", "preparing email & calendar access...", "loading browser & research tools...", "setting up reminders & tasks...", "almost there..." |
| **[cancel]** | Returns to `name` step. |
| On error | Error message + **[try again]** + optional details toggle. |

#### Step: `auth`
Embeds `AuthFlow` component. Optional **[cancel]** returns to name. Optional **[retry]** on error.

#### Step: `done`
| Element | Detail |
|---------|--------|
| Icon | Green checkmark, pop-in animation |
| Heading | `"{name} is ready"` |
| Subtext | "say hi." |
| **[continue]** | Primary. Navigates to `agent-chat` for the new agent. |

### Platform Setup (Tauri + Windows only)

If `checkPlatform()` reports the system is not ready, a platform setup step is shown *before* the name step in the create flow. Sub-states:

| Condition | UI | Actions |
|-----------|----|---------|
| Checking | "checking system" / "making sure everything is ready..." / ProgressBar | — |
| `needs_reboot` | Restart icon, "restart required", explanation text | **[check again]** |
| `virtualization_enabled === false` | Warning icon, "enable virtualization", numbered BIOS steps | **[check again]** |
| `!wsl_installed` | "setting up windows", explanation | **[install WSL2]** (or ProgressBar if busy) |
| WSL installed but not ready | "setting up" / ProgressBar | **[retry]** on error |

Error display: friendly message + optional **[show details]** / **[hide details]** toggle for raw error.

### Version
- `v{version}` centered at bottom. Fetched from `GET /version`.

### Polling
- Refreshes agent list every 5 seconds.
- Lightweight WebSocket per alive agent for real-time activity state (orb color).

---

## Auth Flow (`AuthFlow.svelte`)

OAuth-style code-paste flow for Claude authentication.

| State | UI |
|-------|----|
| Waiting for URL | "starting authentication..." / ProgressBar "waiting..." |
| URL received | Auto-opens browser tab. Shows truncated link (clickable), "paste the code from the browser below", code input (`placeholder="paste code here"`), **[submit]** (disabled if empty) |
| Code submitted | "verifying code..." / ProgressBar "verifying..." |
| Error | Red error text + code input resets for retry |
| Cancel available | **[cancel]** button at bottom |

---

## Agent Detail (`AgentDetail.svelte`)

Single-agent detail view with animated orb and context-sensitive controls.

### Navigation
- **[← back]** button top-left. Returns to `home`.

### Orb ("Creature")
Large 140×140px animated sphere. Pointer tracking with parallax (14px range, lerp 0.015). States:

| State | Colors | Animation |
|-------|--------|-----------|
| `alive` (ready) | Green gradient `#b8ceb0 → #7a9e70 → #5a7e50` | Float 4s + glow pulse 3s + breathe 3s |
| `thinking` / `tool_use` | Amber `#e8d0a0 → #c4a060 → #a08040` | Float 2s + faster breathe 1.2s |
| `booting` (WS not ready) | Lighter green `#c4deb8 → #8ab880 → #6a9e5a` | Float 3s + glow swell 1.5s |
| `authenticating` | Blue `#c0d0e8 → #80a0c4 → #6080a4` | Float 3s + slow pulse 2s |
| `stopping` | Wind-down to gray | Scale to 0.92, glow fades |
| `starting` | Wake-up from gray | Scale from 0.92 to 1.03, glow swells |
| `deleting` | Shrink away | Scale to 0.7, opacity to 0.3 |
| `dead` / `stopped` | Gray `#c4bdb5 → #a09890 → #8b7e74` | No animation, scale 0.92 |

### Label
- Agent name (16px, semibold).
- Status line below (11px). Dynamic values:
  - `"alive"` — fully operational
  - `"waking up..."` — running + authenticated but WS not ready
  - `"not signed in"` — running but not authenticated
  - `"stopped"` — container stopped
  - `"broken — delete and recreate"` — dead status
  - Operation labels: `"stopping..."`, `"starting..."`, `"signing in..."`, `"deleting..."`, `"rebuilding..."`, `"backing up..."`, `"restoring..."`
  - Error messages in red with shake animation

### Auth Panel
- When authenticating, `AuthFlow` appears below the orb.

### Action Buttons
Shown on hover or when agent is not alive. Hidden during operations.

| Condition | Buttons |
|-----------|---------|
| Alive | **[chat]** (primary/filled) |
| Running + not authenticated | **[authenticate]** (primary) |
| Always | **[start]** or **[stop]** |
| Confirming delete | **[confirm]** (trash icon, red) + **[cancel]** (muted) |

### Overflow Menu (⋮)
Opens upward from the action bar.

| Condition | Menu Items |
|-----------|------------|
| Alive | **[console]** — tooltip: "view raw logs" |
| Running | **[restart]** — tooltip: "restart agent" |
| Running | **[rebuild]** — tooltip: "rebuild container from latest image" |
| Running + authenticated | **[authenticate]** — tooltip: "authenticate claude" |
| Always | **[backup]** — tooltip: "export to file" |
| Always | **[load backup]** — tooltip: "restore from file" |
| Divider | — |
| Always | **[delete]** (red) — tooltip: "permanently delete". Two-step confirm. Navigates to `home` after deletion. |

### Polling
- Agent status polled every 5 seconds (skipped while an operation is in progress).

### Version
- `v{version}` centered at bottom.

---

## Chat (`Chat.svelte`)

Real-time conversation interface. Dark theme overlay on top of `AgentDetail`.

### Top Bar
| Element | Detail |
|---------|--------|
| **[← back]** | Returns to agent-detail. Also triggered by Escape (when input empty or not focused). |
| **Agent name** | Title text. |
| **Status dot** | Green = connected, amber = thinking/tool-use, dim = disconnected. Tooltips: "connected", "thinking", "using a tool", "disconnected". |
| **[🔧 tool toggle]** | Wrench icon. Toggles tool/notification message visibility. Tooltip: "show tools" / "hide tools". |

### Message Area
Scrollable output with auto-scroll (sticks to bottom, releases on manual scroll up).

| Line Type | Style |
|-----------|-------|
| User (`> message`) | White/bright text |
| Assistant | Green-tinted `rgba(140, 200, 130, 0.9)` |
| Tool (`[tool_name] input/done`) | Dim white, 11px. Hidden unless tool toggle is on. |
| Notification (`[source] summary`) | Amber-tinted, 11px. Hidden unless tool toggle is on. |
| Error (`error: text`) | Red `rgba(224, 112, 112, 0.9)` |

Each line shows a timestamp (`HH:MM`) on the left.

**Thinking indicator:** Three pulsing green dots when agent is thinking/using tools.

**Empty state:** Three pulsing dots + `"{name} is listening. say something."` (when connected) or `"connecting..."`.

**Reconnect bar:** Amber bar `"reconnecting..."` when WebSocket disconnects after having been connected. 2-second debounce before showing.

### Input Bar
| Element | Detail |
|---------|--------|
| Prompt char | `>` in monospace |
| Textarea | `placeholder="send a message..."` or `"connecting..."` (disabled when disconnected). Auto-resizes up to 120px. |
| **Enter** | Sends message |
| **Shift+Enter** | Newline |
| **Escape** | Back to agent-detail (when input empty or textarea not focused) |

### Text Formatting
Messages are processed by `linkify()`: URLs become clickable links, backtick-wrapped text becomes `<code>`, `**bold**` and `*italic*` are rendered.

### WebSocket Protocol
- Connect to `ws(s)://host/agents/{name}/ws?token={apiKey}`.
- On open: clear messages, reset reconnect delay.
- Inbound events: `history` (bulk load), `status`, `user`, `assistant`, `tool_start`, `tool_end`, `error`, `notification`.
- Outbound: `{ type: "message", text: "..." }`.
- Reconnect with exponential backoff: 1s base, 30s max.
- Max 5000 messages retained.

---

## Console (`Console.svelte`)

Raw Docker container log streaming. Dark theme overlay on top of `AgentDetail`.

### Top Bar
| Element | Detail |
|---------|--------|
| **[← back]** | Returns to agent-detail. Also triggered by Escape. |
| **Agent name** | Title only (no status dot). |

### Log Output
- Streams via SSE (`EventSource` on `GET /agents/{name}/logs?token={apiKey}`).
- ANSI escape codes stripped. URLs linkified.
- Max 5000 lines retained.
- **Empty state:** Three pulsing dots + `"streaming logs..."`.
- **Stream ended:** `"— reconnecting —"` centered, dim text.
- Auto-reconnect with exponential backoff: 1s base, 30s max.

---

## Shared Components

### ProgressBar (`ProgressBar.svelte`)
- Indeterminate animated bar (`.fill` slides left-to-right).
- Optional message below, key-animated on text change.

---

## API Surface

All HTTP requests include `Authorization: Bearer {apiKey}` header.

### REST Endpoints (vestad)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (used for connection validation) |
| GET | `/version` | Returns app version string |
| GET | `/agents` | List all agents → `ListEntry[]` |
| GET | `/agents/{name}` | Agent detail → `AgentInfo` |
| POST | `/agents` | Create agent `{ name }` |
| POST | `/agents/{name}/start` | Start agent |
| POST | `/agents/{name}/stop` | Stop agent |
| POST | `/agents/{name}/restart` | Restart agent |
| POST | `/agents/{name}/rebuild` | Rebuild container from latest image |
| POST | `/agents/{name}/destroy` | Delete agent permanently |
| POST | `/agents/{name}/backup` | Download agent backup → `.tar.gz` blob |
| POST | `/agents/restore?name=&replace=` | Upload backup (gzip body) |
| GET | `/agents/{name}/wait-ready?timeout=` | Block until agent is ready |
| POST | `/agents/{name}/auth` | Start auth → `{ auth_url, session_id }` |
| POST | `/agents/{name}/auth/code` | Submit auth code `{ session_id, code }` |
| GET | `/agents/{name}/logs?token=` | SSE log stream |

### Tauri Invoke Commands
| Command | Description |
|---------|-------------|
| `auto_setup` | Find/configure bundled vestad |
| `platform_check` | Check WSL2/virtualization status (Windows) |
| `platform_setup` | Install/configure WSL2 distro (Windows) |
| `connect_to_server` | Save server config via vesta-common |
| `run_install_script` | Linux: download and install `.deb`/`.rpm` update via `pkexec` |

---

## Data Types

### AgentInfo / ListEntry
```typescript
{
  name: string;
  status: "running" | "stopped" | "dead" | "not_found" | "unknown";
  authenticated: boolean;
  agent_ready: boolean;
  ws_port: number;
  alive: boolean;
  friendly_status: string;
}
```

### PlatformStatus
```typescript
{
  ready: boolean;
  platform: string;
  wsl_installed: boolean;
  virtualization_enabled: boolean | null;
  distro_registered: boolean;
  distro_healthy: boolean;
  services_ready: boolean;
  needs_reboot: boolean;
  message: string;
}
```

### VestaEvent (WebSocket)
```typescript
| { type: "status"; state: "idle" | "thinking" | "tool_use" }
| { type: "user"; text: string }
| { type: "assistant"; text: string }
| { type: "tool_start"; tool: string; input: string }
| { type: "tool_end"; tool: string }
| { type: "error"; text: string }
| { type: "notification"; source: string; summary: string }
| { type: "history"; events: VestaEvent[]; state: AgentActivityState }
```

### LogEvent (SSE)
```typescript
| { kind: "Line"; text: string }
| { kind: "End" }
| { kind: "Error"; message: string }
```

---

## Agent Operations & State Management

Operations tracked per-agent via `store.svelte.ts`. Only one agent can be busy at a time (grid-level guard).

| Operation | Trigger | UI Feedback |
|-----------|---------|-------------|
| `idle` | Default | — |
| `starting` | Start / restart | Orb wake-up animation, "starting..." label |
| `stopping` | Stop | Orb wind-down animation, "stopping..." label |
| `authenticating` | Authenticate | Blue orb, AuthFlow panel, "signing in..." |
| `deleting` | Delete (confirmed) | Orb shrink-away, "deleting..." |
| `rebuilding` | Rebuild | "rebuilding..." label |
| `backing-up` | Backup | "backing up..." label, downloads `.tar.gz` |
| `restoring` | Load backup | "restoring..." label |

Errors displayed as red status text with shake animation. Cleared on next successful status poll.

---

## Error Handling

### Friendly Error Messages (Create Agent)
Raw server errors are mapped to user-friendly text:

| Pattern | Friendly Message |
|---------|-----------------|
| "reboot" | "restart your computer to finish setup, then reopen vesta." |
| "wsl" + "not installed" | WSL install instructions with PowerShell command |
| "wsl" + "virtualization/bios" | BIOS virtualization enable instructions |
| "wsl" + "failed" | WSL install instructions |
| "rootfs" + "download" | "couldn't download vesta. check your internet connection..." |
| "services did not start" | "services didn't start in time. try closing vesta and reopening it." |
| "docker" + "not installed" | "docker is required but not installed..." |
| "docker" + "daemon/not running" | "docker isn't running. start docker desktop..." |
| "failed to pull" | "couldn't download. check your internet connection..." |
| "failed to run cli" | "something went wrong starting vesta. try reinstalling." |
| "setup-token" / "setup_token" | "authentication setup failed..." |
| Other | Raw error shown directly |

All errors have optional **[show details]** toggle for the raw error string.

---

## Keyboard Shortcuts

| Key | Context | Action |
|-----|---------|--------|
| **Enter** | Chat input | Send message |
| **Shift+Enter** | Chat input | Insert newline |
| **Escape** | Chat (input empty or not focused) | Back to agent-detail |
| **Escape** | Console | Back to agent-detail |
| **Escape** | Any open dropdown menu | Close menu |
| **Escape** | Create agent flow (when agents exist) | Cancel, return to home grid |
| **Enter** | Create agent name input | Submit create |
| **Enter** | Connect form | Submit connect |
| **Enter** | Auth code input | Submit code |

---

## Animations

| Animation | Duration | Easing | Used In |
|-----------|----------|--------|---------|
| `breathe` | 2.5s | ease-in-out, infinite | Loading logo |
| `float` | 2–4s | ease-in-out, infinite | Orb idle floating |
| `glow-pulse` | 1.2–3s | ease-in-out, infinite | Orb glow |
| `orb-breathe` | 1.2–3s | ease-in-out, infinite | Orb body scale |
| `glow-swell` | 0.8–1.5s | ease-in-out, infinite | Starting/booting glow |
| `orb-wind-down` | 0.8s | spring, forwards | Stopping |
| `orb-wake-up` | 0.8s | spring, forwards | Starting |
| `shrink-away` | 0.6s | spring, forwards | Deleting |
| `fade-out` | 0.4–0.5s | ease, forwards | Glow/ring fade |
| `viewIn` | 0.6s | spring | View enter |
| `menuIn` | 0.15s | spring | Menu dropdown |
| `fadeSlideIn` | 0.5s | spring | Create agent steps |
| `fadeSlideUp` | 0.3s | spring | Update bar |
| `popIn` | 0.4s | spring-bouncy | Done/platform icons |
| `shake` | 0.3s | ease | Error messages |
| `dot-pulse` | 1.4s | ease-in-out, infinite | Thinking dots |

Spring easings: `--spring`, `--spring-bouncy`, `--spring-snappy` (CSS `linear()` with fallback `cubic-bezier()`).

All animations respect `prefers-reduced-motion: reduce`.

---

## Window Sizing

- Scales to 60% of shortest screen dimension.
- Clamped between 400px and 800px.
- Centered on launch.

---

## Polling & Real-time

| Source | Interval | Purpose |
|--------|----------|---------|
| Agent status (AgentDetail) | 5s | Sync status/authenticated/ready |
| Agent list (Home) | 5s | Refresh agent list + sync mini-orb connections |
| WebSocket (Chat) | Persistent | Real-time messages + activity state |
| WebSocket (Home) | Per alive agent | Activity state for mini-orb color |
| SSE (Console) | Persistent | Real-time log streaming |
| Reconnect backoff | 1s → 30s (×2) | WebSocket and SSE reconnection |

