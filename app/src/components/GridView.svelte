<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { appVersion as appVersionPromise } from "../lib/version";
  import { listAgents, startAgent, stopAgent, restartAgent, deleteAgent, backupAgent, restoreAgent } from "../lib/api";
  import { getAgentOp, busyAgentName, withAgentOp } from "../lib/store.svelte";
  import { save, open } from "@tauri-apps/plugin-dialog";
  import { createAgentConnection, type AgentConnection } from "../lib/ws";
  import type { ListEntry, AgentActivityState } from "../lib/types";

  let appVersion = $state("");

  let {
    onSelect,
    onCreate,
    onChat,
    onConsole,
  }: {
    onSelect: (name: string, wsPort: number) => void;
    onCreate: () => void;
    onChat: (name: string, wsPort: number) => void;
    onConsole: (name: string, wsPort: number) => void;
  } = $props();

  let agents = $state<ListEntry[]>([]);
  let poll: ReturnType<typeof setInterval>;
  let openMenu = $state<string | null>(null);
  let confirming = $state<string | null>(null);

  let connections = new Map<string, { conn: AgentConnection; unsub: () => void }>();
  let activityStates = $state<Record<string, AgentActivityState>>({});

  function syncConnections() {
    const aliveNames = new Set(agents.filter((b) => b.alive).map((b) => `${b.name}:${b.ws_port}`));

    for (const [key, entry] of connections) {
      if (!aliveNames.has(key)) {
        entry.unsub();
        entry.conn.disconnect();
        connections.delete(key);
        const agentName = key.split(":")[0];
        const { [agentName]: _, ...rest } = activityStates;
        activityStates = rest;
      }
    }

    for (const agent of agents) {
      const key = `${agent.name}:${agent.ws_port}`;
      if (agent.alive && !connections.has(key)) {
        const conn = createAgentConnection(agent.name);
        const unsub = conn.agentState.subscribe((v: AgentActivityState) => {
          if (activityStates[agent.name] !== v) activityStates[agent.name] = v;
        });
        conn.connect();
        connections.set(key, { conn, unsub });
      }
    }
  }

  function teardownConnections() {
    for (const [, entry] of connections) {
      entry.unsub();
      entry.conn.disconnect();
    }
    connections.clear();
  }

  async function refresh() {
    try {
      const next = await listAgents();
      if (JSON.stringify(next) !== JSON.stringify(agents)) {
        agents = next;
        syncConnections();
      }
    } catch (e) {
      console.warn("failed to list agents:", e);
    }
  }

  onMount(async () => {
    refresh();
    poll = setInterval(refresh, 5000);
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);
    appVersion = await appVersionPromise;
  });

  onDestroy(() => {
    clearInterval(poll);
    teardownConnections();
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  });

  function onDocClick(e: MouseEvent) {
    if (openMenu && !(e.target as Element)?.closest?.(".menu-wrapper")) {
      openMenu = null;
      confirming = null;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && openMenu) {
      openMenu = null;
      confirming = null;
    }
  }

  function orbClass(agent: ListEntry, activity?: AgentActivityState): string {
    if (agent.status === "dead") return "dead";
    if (agent.status === "running" && agent.authenticated && agent.agent_ready) {
      if (activity === "thinking" || activity === "tool_use") return "active";
      return "alive";
    }
    if (agent.status === "running" && agent.authenticated) return "booting";
    if (agent.status === "running" && !agent.authenticated) return "auth";
    return "dead";
  }

  async function handleToggle(agent: ListEntry) {
    if (busyAgentName()) return;
    const op = agent.status === "running" ? "stopping" : "starting";
    const fallback = agent.status === "running" ? "failed to stop" : "failed to start";
    await withAgentOp(agent.name, op, async () => {
      if (agent.status === "running") {
        await stopAgent(agent.name);
      } else {
        await startAgent(agent.name);
      }
      await refresh();
    }, fallback);
  }

  async function handleRestart(agent: ListEntry) {
    if (busyAgentName()) return;
    await withAgentOp(agent.name, "starting", async () => {
      await restartAgent(agent.name);
      await refresh();
    }, "failed to restart");
  }

  async function handleBackup(agent: ListEntry) {
    const date = new Date().toISOString().slice(0, 10);
    const path = await save({
      defaultPath: `${agent.name}-backup-${date}.tar.gz`,
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
    });
    if (!path) return;
    await withAgentOp(agent.name, "backing-up", async () => {
      await backupAgent(agent.name, path);
      await refresh();
    }, "backup failed");
  }

  async function handleRestore(agent: ListEntry) {
    const path = await open({
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
      multiple: false,
      directory: false,
    });
    if (!path) return;
    await withAgentOp(agent.name, "restoring", async () => {
      await restoreAgent(path, agent.name, true);
      await refresh();
    }, "restore failed");
  }

  async function handleDelete(agentName: string) {
    if (confirming !== agentName) {
      confirming = agentName;
      return;
    }
    confirming = null;
    await withAgentOp(agentName, "deleting", async () => {
      await deleteAgent(agentName);
      await refresh();
    }, "failed to delete");
  }

  function menuAction(fn: () => void) {
    return (e: MouseEvent) => { e.stopPropagation(); openMenu = null; fn(); };
  }

  let gridCols = $derived(agents.length === 1 ? 1 : agents.length === 2 ? 2 : 3);

  function isAgentBusy(agentName: string): boolean {
    return getAgentOp(agentName).operation !== "idle";
  }
</script>

<div class="grid-view" class:centered={gridCols < 3}>
  <button class="add-btn" onclick={onCreate} aria-label="new agent" data-tip="new agent">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M12 5v14M5 12h14"/>
    </svg>
  </button>
  <div class="grid cols-{gridCols}" class:few={gridCols < 3}>
    {#each agents as agent}
      <div class="card-wrapper">
        <button class="card" class:busy={isAgentBusy(agent.name)} onclick={() => onSelect(agent.name, agent.ws_port)}>
          <div class="mini-orb-container {orbClass(agent, activityStates[agent.name])}">
            <div class="mini-orb-glow"></div>
            <div class="mini-orb-body">
              <div class="mini-orb-highlight"></div>
            </div>
          </div>
          <span class="card-name">{agent.name}</span>
        </button>
        <div class="menu-wrapper">
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="menu-trigger"
            class:visible={openMenu === agent.name}
            onclick={(e) => { e.stopPropagation(); openMenu = openMenu === agent.name ? null : agent.name; confirming = null; }}
            aria-label="more options"
            data-tip="actions"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
              <circle cx="8" cy="3" r="1.5"/>
              <circle cx="8" cy="8" r="1.5"/>
              <circle cx="8" cy="13" r="1.5"/>
            </svg>
          </div>
          {#if openMenu === agent.name}
            <div class="menu-dropdown">
              {#if confirming === agent.name}
                <button class="menu-item danger" onclick={menuAction(() => handleDelete(agent.name))}>confirm delete</button>
                <button class="menu-item muted" onclick={menuAction(() => { confirming = null; })}>cancel</button>
              {:else}
                {#if agent.alive}
                  <button class="menu-item" onclick={menuAction(() => onChat(agent.name, agent.ws_port))}>chat</button>
                  <button class="menu-item" onclick={menuAction(() => onConsole(agent.name, agent.ws_port))}>console</button>
                {/if}
                <button class="menu-item" disabled={!!busyAgentName()} onclick={menuAction(() => handleToggle(agent))}>{agent.status === "running" ? "stop" : "start"}</button>
                {#if agent.status === "running"}
                  <button class="menu-item" disabled={!!busyAgentName()} onclick={menuAction(() => handleRestart(agent))}>restart</button>
                {/if}
                <button class="menu-item" disabled={!!busyAgentName()} onclick={menuAction(() => handleBackup(agent))}>backup</button>
                <button class="menu-item" disabled={!!busyAgentName()} onclick={menuAction(() => handleRestore(agent))}>load backup</button>
                <div class="menu-divider"></div>
                <button class="menu-item danger" disabled={!!busyAgentName()} onclick={(e: MouseEvent) => { e.stopPropagation(); handleDelete(agent.name); }}>delete</button>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    {/each}
  </div>
  {#if appVersion}
    <span class="version">v{appVersion}</span>
  {/if}
</div>

<style>
  .grid-view {
    position: relative;
    width: 100%;
    height: 100%;
    padding: 8px 12px 8px;
    overflow-y: auto;
    animation: viewIn 0.6s var(--spring);
  }

  .grid-view.centered {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .grid-view::-webkit-scrollbar { width: 6px; }
  .grid-view::-webkit-scrollbar-track { background: transparent; }
  .grid-view::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.08); border-radius: 3px; }

  @keyframes viewIn {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }

  .add-btn {
    position: absolute;
    top: 4px;
    right: 8px;
    z-index: 10;
    width: 44px;
    height: 44px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.7);
    color: #5a5450;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
  }

  .add-btn:hover {
    background: rgba(255, 255, 255, 0.95);
    border-color: rgba(0, 0, 0, 0.12);
    color: #1a1816;
    transform: translateY(-1px);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  }

  .add-btn:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .grid {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 8px;
    width: 100%;
    padding-top: 40px;
  }

  .grid.few {
    padding-top: 0;
  }

  .grid.cols-1 {
    max-width: 220px;
    margin: 0 auto;
  }

  .grid.cols-2 {
    max-width: 440px;
    margin: 0 auto;
  }

  .card-wrapper {
    position: relative;
    width: calc((100% - 16px) / 3);
  }

  .grid.cols-1 .card-wrapper {
    width: 100%;
  }

  .grid.cols-2 .card-wrapper {
    width: calc((100% - 8px) / 2);
  }

  .card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    width: 100%;
    aspect-ratio: 1;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 12px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    transition: all 0.2s var(--spring-bouncy);
    font-family: inherit;
    padding: 8px 4px;
  }

  .card:hover {
    background: rgba(255, 255, 255, 0.8);
    border-color: rgba(0, 0, 0, 0.1);
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  }

  .card:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .card.busy {
    opacity: 0.5;
    pointer-events: none;
  }

  /* Show menu trigger on card hover */
  .card-wrapper:hover .menu-trigger,
  .menu-trigger.visible {
    opacity: 1;
  }

  /* --- Mini Orb --- */
  @property --mini-c1 { syntax: "<color>"; inherits: true; initial-value: #b8ceb0; }
  @property --mini-c2 { syntax: "<color>"; inherits: true; initial-value: #7a9e70; }
  @property --mini-c3 { syntax: "<color>"; inherits: true; initial-value: #5a7e50; }
  @property --mini-glow { syntax: "<color>"; inherits: true; initial-value: rgba(138, 180, 120, 0.35); }

  .mini-orb-container {
    position: relative;
    width: 36px;
    height: 36px;
    transition: filter 0.8s var(--spring), width 0.3s var(--spring), height 0.3s var(--spring);
  }

  .cols-1 .mini-orb-container {
    width: 56px;
    height: 56px;
  }

  .cols-2 .mini-orb-container {
    width: 44px;
    height: 44px;
  }

  .mini-orb-body {
    position: absolute;
    inset: 6px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, var(--mini-c1), var(--mini-c2) 50%, var(--mini-c3));
    box-shadow:
      inset 0 -3px 8px rgba(0, 0, 0, 0.15),
      inset 0 2px 4px rgba(255, 255, 255, 0.15);
    transition: --mini-c1 0.8s var(--spring), --mini-c2 0.8s var(--spring), --mini-c3 0.8s var(--spring), box-shadow 0.8s var(--spring);
  }

  .mini-orb-highlight {
    position: absolute;
    top: 18%;
    left: 28%;
    width: 28%;
    height: 20%;
    border-radius: 50%;
    background: radial-gradient(ellipse, rgba(255, 255, 255, 0.55), transparent);
    filter: blur(1px);
    transition: opacity 0.8s var(--spring);
  }

  .mini-orb-glow {
    position: absolute;
    inset: -2px;
    border-radius: 50%;
    background: radial-gradient(circle, var(--mini-glow), transparent 70%);
    filter: blur(6px);
    transition: opacity 0.8s var(--spring), --mini-glow 0.8s var(--spring);
  }

  /* Alive */
  .mini-orb-container.alive {
    animation: float 4s ease-in-out infinite;
  }

  .mini-orb-container.alive .mini-orb-glow {
    animation: glow-pulse 3s ease-in-out infinite;
  }

  .mini-orb-container.alive .mini-orb-body {
    animation: orb-breathe 3s ease-in-out infinite;
  }

  /* Active — thinking / tool use (amber) */
  .mini-orb-container.active {
    --mini-c1: #e8d0a0;
    --mini-c2: #c4a060;
    --mini-c3: #a08040;
    --mini-glow: rgba(200, 170, 100, 0.4);
    animation: float 2s ease-in-out infinite;
  }

  .mini-orb-container.active .mini-orb-body {
    animation: orb-breathe 1.2s ease-in-out infinite;
  }

  .mini-orb-container.active .mini-orb-glow {
    animation: glow-pulse 1.2s ease-in-out infinite;
  }

  /* Booting — alive but WS not ready */
  .mini-orb-container.booting {
    --mini-c1: #c4deb8;
    --mini-c2: #8ab880;
    --mini-c3: #6a9e5a;
    animation: float 3s ease-in-out infinite;
  }

  .mini-orb-container.booting .mini-orb-body {
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .mini-orb-container.booting .mini-orb-glow {
    animation: glow-swell 1.5s ease-in-out infinite;
  }

  /* Auth — running but not signed in */
  .mini-orb-container.auth {
    --mini-c1: #c0d0e8;
    --mini-c2: #80a0c4;
    --mini-c3: #6080a4;
    --mini-glow: rgba(100, 150, 200, 0.35);
    animation: float 3s ease-in-out infinite;
  }

  .mini-orb-container.auth .mini-orb-body {
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .mini-orb-container.auth .mini-orb-glow {
    animation: glow-pulse 2s ease-in-out infinite;
  }

  /* Dead / Stopped */
  .mini-orb-container.dead {
    --mini-c1: #c4bdb5;
    --mini-c2: #a09890;
    --mini-c3: #8b7e74;
    --mini-glow: rgba(160, 152, 144, 0.2);
  }

  .mini-orb-container.dead .mini-orb-body {
    box-shadow:
      inset 0 -3px 8px rgba(0, 0, 0, 0.1),
      inset 0 2px 4px rgba(255, 255, 255, 0.05);
    transform: scale(0.92);
  }

  .mini-orb-container.dead .mini-orb-glow {
    opacity: 0.15;
  }

  .mini-orb-container.dead .mini-orb-highlight {
    opacity: 0.3;
  }

  @keyframes float {
    0%, 100% { translate: 0 0; }
    50% { translate: 0 -2px; }
  }

  @keyframes glow-pulse {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.08); }
  }

  @keyframes orb-breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.03); }
  }

  @keyframes glow-swell {
    0%, 100% { opacity: 0.4; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.12); }
  }

  .card-name {
    font-size: 11px;
    font-weight: 550;
    color: #3d3a36;
    letter-spacing: -0.01em;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    user-select: none;
  }

  .cols-1 .card-name {
    font-size: 14px;
  }

  .cols-2 .card-name {
    font-size: 12px;
  }

  /* --- Three-dot menu --- */
  .menu-wrapper {
    position: absolute;
    top: 4px;
    right: 4px;
  }

  .menu-trigger {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    corner-shape: squircle;
    cursor: pointer;
    color: #a09890;
    opacity: 0;
    transition: opacity 0.15s ease, background 0.12s ease, color 0.12s ease;
  }

  .menu-trigger:hover {
    background: rgba(0, 0, 0, 0.06);
    color: #5a5450;
  }

  .menu-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    display: flex;
    flex-direction: column;
    min-width: 120px;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 10px;
    corner-shape: squircle;
    padding: 4px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    animation: menuIn 0.15s var(--spring);
    z-index: 20;
  }

  @keyframes menuIn {
    from { opacity: 0; transform: translateY(-4px) scale(0.96); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .menu-divider {
    height: 1px;
    background: rgba(0, 0, 0, 0.06);
    margin: 2px 8px;
  }

  .menu-item {
    padding: 8px 12px;
    min-height: 32px;
    border: none;
    background: transparent;
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    color: #5a5450;
    cursor: pointer;
    border-radius: 6px;
    corner-shape: squircle;
    text-align: left;
    transition: background 0.12s ease;
    display: flex;
    align-items: center;
  }

  .menu-item:hover {
    background: rgba(0, 0, 0, 0.05);
  }

  .menu-item.danger {
    color: #c45450;
  }

  .menu-item.danger:hover {
    background: rgba(196, 84, 80, 0.08);
  }

  .menu-item.muted {
    color: #a09890;
  }

  .menu-item:disabled {
    opacity: 0.25;
    cursor: not-allowed;
    pointer-events: none;
  }

  .version {
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 10px;
    font-weight: 400;
    letter-spacing: 0.02em;
    color: #c4bdb5;
    user-select: none;
    pointer-events: none;
  }

  @media (prefers-color-scheme: dark) {
    .grid-view::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.08); }

    .add-btn {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.06);
      color: #b0a8a0;
    }
    .add-btn:hover {
      background: rgba(255, 255, 255, 0.14);
      border-color: rgba(255, 255, 255, 0.1);
      color: #e8e0d8;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
    }

    .card {
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.06);
    }

    .card:hover {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.1);
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    }

    .card-name {
      color: #e8e0d8;
    }

    .menu-trigger {
      color: #6a625a;
    }
    .menu-trigger:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #a09890;
    }

    .menu-dropdown {
      background: rgba(40, 38, 36, 0.9);
      border-color: rgba(255, 255, 255, 0.08);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }

    .menu-item {
      color: #b0a8a0;
    }
    .menu-item:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #e8e0d8;
    }
    .menu-item.danger {
      color: #e07070;
    }
    .menu-item.danger:hover {
      background: rgba(224, 112, 112, 0.1);
      color: #f08080;
    }
    .menu-item.muted {
      color: #8a8078;
    }
    .menu-divider {
      background: rgba(255, 255, 255, 0.06);
    }
    .version {
      color: #5a5450;
    }
  }
</style>
