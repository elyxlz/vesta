<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { appVersion as appVersionPromise } from "../lib/version";
  import type { AgentConnection } from "../lib/ws";
  import { agentStatus, startAgent, stopAgent, restartAgent, rebuildAgent, deleteAgent, authenticate, backupAgent, restoreAgent } from "../lib/api";
  import { getAgentOp, setAgentError, withAgentOp, type AgentOperation } from "../lib/store.svelte";
  import { save, open } from "@tauri-apps/plugin-dialog";
  import type { AgentStatus, AgentActivityState } from "../lib/types";
  import AuthFlow from "./AuthFlow.svelte";

  let {
    name,
    connection,
    onChat,
    onConsole,
    onDestroyed,
    onBack,
  }: {
    name: string;
    connection: AgentConnection;
    onChat: () => void;
    onConsole: () => void;
    onDestroyed: () => void;
    onBack: () => void;
  } = $props();

  let appVersion = $state("");
  let statusLoaded = $state(false);
  let status = $state<AgentStatus>("unknown");
  let authenticated = $state(false);
  let agentReady = $state(false);
  let confirming = $state(false);
  let menuOpen = $state(false);
  let hovered = $state(false);
  let poll: ReturnType<typeof setInterval>;
  let creatureEl: HTMLDivElement;
  let leaveTimer: ReturnType<typeof setTimeout> | null = null;
  let cachedRect: DOMRect | null = null;
  let orbEl: HTMLDivElement;
  let targetX = 0, targetY = 0;
  let currentX = 0, currentY = 0;
  let rafId = 0;
  const LERP = 0.015;
  const SNAP = 0.5;

  let agentOp = $derived(getAgentOp(name));
  let operation = $derived(agentOp.operation);
  let errorMsg = $derived(agentOp.error);
  let stopping = $derived(operation === "stopping");
  let starting = $derived(operation === "starting");
  let authenticating = $derived(operation === "authenticating");
  let deleting = $derived(operation === "deleting");
  let backingUp = $derived(operation === "backing-up");
  let restoring = $derived(operation === "restoring");
  let busy = $derived(operation !== "idle");

  let agentStateVal = $state<AgentActivityState>("idle");
  let idleTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    const unsub = connection.agentState.subscribe((v: AgentActivityState) => {
      if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
      if (v === "idle") {
        idleTimer = setTimeout(() => { agentStateVal = v; }, 400);
      } else {
        agentStateVal = v;
      }
    });
    return () => { unsub(); if (idleTimer) clearTimeout(idleTimer); };
  });

  function orbLoop() {
    if (!orbEl) { rafId = 0; return; }
    currentX += (targetX - currentX) * LERP;
    currentY += (targetY - currentY) * LERP;
    const done = Math.abs(targetX - currentX) < SNAP && Math.abs(targetY - currentY) < SNAP;
    if (done) { currentX = targetX; currentY = targetY; }
    orbEl.style.transform = `translate3d(${currentX}px,${currentY}px,0)`;
    if (done) { rafId = 0; return; }
    rafId = requestAnimationFrame(orbLoop);
  }

  function startLoop() {
    if (!rafId) rafId = requestAnimationFrame(orbLoop);
  }

  function onOrbEnter() {
    if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null; }
    hovered = true;
    cachedRect = creatureEl?.getBoundingClientRect() ?? null;
  }

  function onOrbMove(e: PointerEvent) {
    if (!alive || !cachedRect || !orbEl) return;
    targetX = (e.clientX - cachedRect.left - cachedRect.width / 2) / (cachedRect.width / 2) * 14;
    targetY = (e.clientY - cachedRect.top - cachedRect.height / 2) / (cachedRect.height / 2) * 14;
    startLoop();
  }

  function onOrbLeave() {
    leaveTimer = setTimeout(() => {
      hovered = false;
      targetX = 0;
      targetY = 0;
      startLoop();
    }, 150);
  }

  async function syncStatus() {
    try {
      const info = await agentStatus(name);
      if (status !== info.status) status = info.status;
      if (authenticated !== info.authenticated) authenticated = info.authenticated;
      if (agentReady !== info.agent_ready) agentReady = info.agent_ready;
      if (errorMsg) setAgentError(name, "");
    } catch {
      if (status !== "unknown") status = "unknown";
      if (authenticated) authenticated = false;
      if (agentReady) agentReady = false;
    }
    if (!statusLoaded) statusLoaded = true;
  }

  async function refresh() {
    if (busy) return;
    await syncStatus();
  }

  function onDocClick(e: MouseEvent) {
    if (menuOpen && !(e.target as Element)?.closest?.(".menu-wrapper")) {
      menuOpen = false;
      confirming = false;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && menuOpen) {
      menuOpen = false;
      confirming = false;
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
    if (leaveTimer) clearTimeout(leaveTimer);
    if (idleTimer) { clearTimeout(idleTimer); idleTimer = null; }
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  });

  async function toggleRun() {
    const wasStopping = running;
    await withAgentOp(name, running ? "stopping" : "starting", async () => {
      if (wasStopping) {
        await stopAgent(name);
      } else {
        await startAgent(name);
        connection.resetReconnect();
      }
      await syncStatus();
    }, wasStopping ? "failed to stop" : "failed to start");
  }

  async function destroy() {
    if (!confirming) {
      confirming = true;
      return;
    }
    await withAgentOp(name, "deleting", async () => {
      await deleteAgent(name);
      onDestroyed();
    }, "failed to delete");
    confirming = false;
  }

  function cancelDestroy() {
    confirming = false;
  }

  async function handleAuth() {
    await withAgentOp(name, "authenticating", async () => {
      await authenticate(name);
      if (running) {
        await restartAgent(name);
      } else {
        await startAgent(name);
      }
      connection.resetReconnect();
      await syncStatus();
    }, "authentication failed");
  }

  async function handleRestart() {
    await withAgentOp(name, "starting", async () => {
      await restartAgent(name);
      connection.resetReconnect();
      await syncStatus();
    }, "failed to restart");
  }

  async function handleRebuild() {
    await withAgentOp(name, "rebuilding", async () => {
      await rebuildAgent(name);
      connection.resetReconnect();
      await syncStatus();
    }, "failed to rebuild");
  }

  async function handleBackup() {
    if (busy) return;
    setAgentError(name, "");
    const date = new Date().toISOString().slice(0, 10);
    const path = await save({
      defaultPath: `${name}-backup-${date}.tar.gz`,
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
    });
    if (!path) return;
    await withAgentOp(name, "backing-up", async () => {
      await backupAgent(name, path);
      connection.resetReconnect();
      await syncStatus();
    }, "backup failed");
  }

  async function handleRestore() {
    if (busy) return;
    setAgentError(name, "");
    const path = await open({
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
      multiple: false,
      directory: false,
    });
    if (!path) return;
    await withAgentOp(name, "restoring", async () => {
      await restoreAgent(path, name, true);
      connection.resetReconnect();
      await syncStatus();
    }, "restore failed");
  }

  let running = $derived(status === "running");
  let dead = $derived(status === "dead");
  let alive = $derived(running && authenticated);
  let operational = $derived(alive && !deleting && !stopping);
  let fullyAlive = $derived(operational && agentReady);
  let showActions = $derived(statusLoaded && (hovered || !alive || confirming || menuOpen));

  const OP_LABELS: Record<AgentOperation, string> = {
    "idle": "", "stopping": "stopping...", "starting": "starting...",
    "authenticating": "signing in...", "deleting": "deleting...",
    "rebuilding": "rebuilding...", "backing-up": "backing up...", "restoring": "restoring...",
  };
  let statusLabel = $derived(
    errorMsg ? errorMsg
    : OP_LABELS[operation] || (fullyAlive ? "alive" : operational ? "waking up..." : running ? "not signed in" : dead ? "broken — delete and recreate" : "stopped")
  );

</script>

<div
  class="agent-view"
  role="group"
  aria-label="Controls"
>
  <button class="back-btn" onclick={onBack} aria-label="back" data-tip="back">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <polyline points="15 18 9 12 15 6"/>
    </svg>
  </button>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="creature-area"
    bind:this={creatureEl}
    onpointerenter={onOrbEnter}
    onpointerleave={onOrbLeave}
    onpointermove={onOrbMove}
  >
    <div class="orb-container" class:orb-loading={!statusLoaded} bind:this={orbEl} class:alive={fullyAlive} class:booting={operational && !agentReady} class:dead={statusLoaded && ((!alive && !starting && !authenticating) || deleting || dead)} class:stopping class:starting class:authenticating class:deleting class:thinking={agentStateVal === 'thinking'} class:tool-use={agentStateVal === 'tool_use'}>
      <div class="orb-glow"></div>
      <div class="orb-body">
        <div class="orb-highlight"></div>
      </div>
      <div class="orb-ring"></div>
      <div class="orb-ambient"></div>
    </div>

    <div class="label">
      <span class="name">{name}</span>
      <span class="status" class:alive={fullyAlive} class:error={!!errorMsg} title={errorMsg || ""}>
        {#if !statusLoaded}
          &nbsp;
        {:else}
          {statusLabel}
        {/if}
      </span>
    </div>

    {#if authenticating}
      <div class="auth-panel">
        <AuthFlow />
      </div>
    {/if}

    <div class="actions" class:visible={showActions && !deleting && !stopping && !starting && !authenticating && !backingUp && !restoring} inert={!showActions || deleting || stopping || starting || authenticating || backingUp || restoring}>
      {#if confirming}
        <button class="action-btn danger" disabled={busy} onclick={destroy}>
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          confirm
        </button>
        <button class="action-btn muted" disabled={busy} onclick={cancelDestroy}>cancel</button>
      {:else}
        {#if alive}
          <button class="action-btn primary" onclick={onChat} data-tip="open chat">chat</button>
        {:else if running && !authenticated}
          <button class="action-btn primary" disabled={busy} onclick={handleAuth} data-tip="authenticate claude">authenticate</button>
        {/if}
        <button class="action-btn" disabled={busy} onclick={toggleRun} data-tip={running ? "stop" : "start"}>
          {running ? "stop" : "start"}
        </button>
        <div class="menu-wrapper">
          <button class="action-btn menu-trigger" onclick={() => (menuOpen = !menuOpen)} aria-label="more options">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor">
              <circle cx="8" cy="3" r="1.5"/>
              <circle cx="8" cy="8" r="1.5"/>
              <circle cx="8" cy="13" r="1.5"/>
            </svg>
          </button>
          {#if menuOpen}
            <div class="menu-dropdown">
              {#if alive}
                <button class="menu-item" onclick={() => { menuOpen = false; onConsole(); }} data-tip="view raw logs">console</button>
              {/if}
              {#if running}
                <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleRestart(); }} data-tip="restart agent">restart</button>
                <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleRebuild(); }} data-tip="rebuild container from latest image">rebuild</button>
              {/if}
              {#if running && authenticated}
                <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleAuth(); }} data-tip="authenticate claude">authenticate</button>
              {/if}
              <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleBackup(); }} data-tip="export to file">backup</button>
              <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleRestore(); }} data-tip="restore from file">load backup</button>
              <div class="menu-divider"></div>
              <button class="menu-item danger" disabled={busy} onclick={() => { menuOpen = false; destroy(); }} data-tip="permanently delete">delete</button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>

  {#if appVersion}
    <span class="version">v{appVersion}</span>
  {/if}
</div>

<style>
  .agent-view {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    animation: viewIn 0.6s var(--spring);
  }

  .back-btn {
    position: absolute;
    top: 4px;
    left: 8px;
    z-index: 10;
    width: 44px;
    height: 44px;
    border: none;
    border-radius: 8px;
    corner-shape: squircle;
    background: transparent;
    color: rgba(0, 0, 0, 0.2);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
  }

  .back-btn:hover {
    background: rgba(0, 0, 0, 0.04);
    color: rgba(0, 0, 0, 0.45);
  }

  .back-btn:active {
    transform: scale(0.97);
  }

  @media (prefers-color-scheme: dark) {
    .back-btn {
      color: rgba(255, 255, 255, 0.25);
    }
    .back-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      color: rgba(255, 255, 255, 0.6);
    }
  }

  @keyframes viewIn {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }

  .creature-area {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 20px;
    padding: min(80px, 8vh) min(180px, 20vw) min(120px, 15vh);
  }

  /* --- Orb --- */
  .orb-container {
    position: relative;
    width: 140px;
    height: 140px;
    will-change: transform;
    transition: filter 0.8s var(--spring);
  }

  .orb-container.orb-loading {
    opacity: 0;
  }

  .orb-container.orb-loading,
  .orb-container.orb-loading * {
    transition: none !important;
    animation: none !important;
  }

  @property --orb-c1 { syntax: "<color>"; inherits: true; initial-value: #b8ceb0; }
  @property --orb-c2 { syntax: "<color>"; inherits: true; initial-value: #7a9e70; }
  @property --orb-c3 { syntax: "<color>"; inherits: true; initial-value: #5a7e50; }
  @property --orb-glow { syntax: "<color>"; inherits: true; initial-value: rgba(138, 180, 120, 0.35); }
  @property --orb-ambient { syntax: "<color>"; inherits: true; initial-value: rgba(138, 180, 120, 0.08); }

  .orb-body {
    position: absolute;
    inset: 20px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, var(--orb-c1), var(--orb-c2) 50%, var(--orb-c3));
    box-shadow:
      inset 0 -8px 20px rgba(0, 0, 0, 0.15),
      inset 0 4px 12px rgba(255, 255, 255, 0.15);
    transition: --orb-c1 0.8s var(--spring), --orb-c2 0.8s var(--spring), --orb-c3 0.8s var(--spring), box-shadow 0.8s var(--spring), transform 0.8s var(--spring);
  }

  .orb-highlight {
    position: absolute;
    top: 18%;
    left: 28%;
    width: 28%;
    height: 20%;
    border-radius: 50%;
    background: radial-gradient(ellipse, rgba(255, 255, 255, 0.55), transparent);
    filter: blur(2px);
    transition: opacity 0.8s var(--spring);
  }

  .orb-glow {
    position: absolute;
    inset: -5px;
    border-radius: 50%;
    background: radial-gradient(circle, var(--orb-glow), transparent 70%);
    filter: blur(18px);
    transition: opacity 0.8s var(--spring), --orb-glow 0.8s var(--spring);
  }

  .orb-ring {
    position: absolute;
    inset: 14px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: border-color 0.8s var(--spring);
  }

  .orb-ambient {
    position: absolute;
    inset: -30px;
    border-radius: 50%;
    background: radial-gradient(circle, var(--orb-ambient), transparent 70%);
    transition: opacity 0.8s var(--spring), --orb-ambient 0.8s var(--spring);
  }

  /* Alive state */
  .orb-container.alive {
    animation: float 4s ease-in-out infinite;
  }

  .orb-container.alive .orb-glow {
    animation: glow-pulse 3s ease-in-out infinite;
  }

  .orb-container.alive .orb-body {
    animation: orb-breathe 3s ease-in-out infinite;
  }

  @keyframes float {
    0%, 100% { translate: 0 0; }
    50% { translate: 0 -6px; }
  }

  @keyframes glow-pulse {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.08); }
  }

  @keyframes orb-breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.03); }
  }

  /* Active state (thinking + tool use) — amber */
  .orb-container.thinking,
  .orb-container.tool-use {
    --orb-c1: #e8d0a0;
    --orb-c2: #c4a060;
    --orb-c3: #a08040;
    --orb-glow: rgba(200, 170, 100, 0.4);
    --orb-ambient: rgba(200, 170, 100, 0.12);
    animation: float 2s ease-in-out infinite;
  }

  .orb-container.thinking .orb-body,
  .orb-container.tool-use .orb-body {
    animation: orb-breathe 1.2s ease-in-out infinite;
  }

  .orb-container.thinking .orb-glow,
  .orb-container.tool-use .orb-glow {
    animation: glow-pulse 1.2s ease-in-out infinite;
  }

  /* Stopping state */
  .orb-container.stopping .orb-body {
    animation: orb-wind-down 0.8s var(--spring) forwards;
  }

  .orb-container.stopping .orb-glow {
    animation: fade-out 0.5s ease forwards;
  }

  .orb-container.stopping .orb-ring {
    animation: fade-out 0.5s ease forwards;
  }

  @keyframes orb-wind-down {
    to { transform: scale(0.92); background: radial-gradient(circle at 38% 32%, #c4bdb5, #a09890 50%, #8b7e74); }
  }

  /* Starting state */
  .orb-container.starting .orb-body {
    animation: orb-wake-up 0.8s var(--spring) forwards;
  }

  .orb-container.starting .orb-glow {
    animation: glow-swell 0.8s ease-in-out infinite;
  }

  @keyframes orb-wake-up {
    from { transform: scale(0.92); }
    to { transform: scale(1.03); }
  }

  @keyframes glow-swell {
    0%, 100% { opacity: 0.4; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.12); }
  }

  /* Booting state — alive but WS not ready yet */
  .orb-container.booting {
    animation: float 3s ease-in-out infinite;
  }

  .orb-container.booting {
    --orb-c1: #c4deb8;
    --orb-c2: #8ab880;
    --orb-c3: #6a9e5a;
  }

  .orb-container.booting .orb-body {
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .orb-container.booting .orb-glow {
    animation: glow-swell 1.5s ease-in-out infinite;
  }

  /* Authenticating state — slow pulse, waiting on user */
  .orb-container.authenticating {
    --orb-c1: #c0d0e8;
    --orb-c2: #80a0c4;
    --orb-c3: #6080a4;
    --orb-glow: rgba(100, 150, 200, 0.35);
    --orb-ambient: rgba(100, 150, 200, 0.1);
    animation: float 3s ease-in-out infinite;
  }

  .orb-container.authenticating .orb-body {
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .orb-container.authenticating .orb-glow {
    animation: glow-pulse 2s ease-in-out infinite;
  }

  /* Deleting state */
  .orb-container.deleting {
    animation: shrink-away 0.6s var(--spring) forwards;
  }

  .orb-container.deleting .orb-glow {
    animation: fade-out 0.4s ease forwards;
  }

  @keyframes shrink-away {
    to { transform: scale(0.7); opacity: 0.3; }
  }

  @keyframes fade-out {
    to { opacity: 0; }
  }

  /* Dead state */
  .orb-container.dead {
    --orb-c1: #c4bdb5;
    --orb-c2: #a09890;
    --orb-c3: #8b7e74;
    --orb-glow: rgba(160, 152, 144, 0.2);
  }

  .orb-container.dead .orb-body {
    box-shadow:
      inset 0 -8px 20px rgba(0, 0, 0, 0.1),
      inset 0 4px 12px rgba(255, 255, 255, 0.05);
    transform: scale(0.92);
  }

  .orb-container.dead .orb-glow {
    opacity: 0.15;
  }

  .orb-container.dead .orb-highlight {
    opacity: 0.3;
  }

  .orb-container.dead .orb-ambient {
    opacity: 0.2;
  }

  .orb-container.dead .orb-ring {
    border-color: rgba(255, 255, 255, 0.03);
  }

  /* --- Label --- */
  .label {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    max-width: 100%;
    user-select: none;
  }

  .name {
    font-size: 16px;
    font-weight: 550;
    color: #3d3a36;
    letter-spacing: -0.01em;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .status {
    font-size: 11px;
    font-weight: 450;
    color: #807870;
    letter-spacing: 0.04em;
    text-transform: lowercase;
    max-width: 200px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    user-select: none;
  }

  .status.alive {
    color: #7a9e70;
  }

  .status.error {
    color: #c45450;
    animation: shake 0.3s ease;
  }

  @keyframes shake {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(-3px); }
    75% { transform: translateX(3px); }
  }

  /* --- Auth panel --- */
  .auth-panel {
    width: 280px;
    animation: viewIn 0.3s var(--spring);
  }

  /* --- Actions --- */
  .actions {
    display: flex;
    gap: 8px;
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.3s var(--spring), transform 0.3s var(--spring);
    pointer-events: none;
  }

  .actions.visible {
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
  }

  .action-btn {
    padding: 8px 16px;
    min-height: 36px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(8px);
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    color: #5a5450;
    cursor: pointer;
    transition: all 0.15s var(--spring-bouncy);
    letter-spacing: 0.01em;
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .action-btn:hover {
    background: rgba(255, 255, 255, 0.95);
    border-color: rgba(0, 0, 0, 0.12);
    color: #1a1816;
    transform: translateY(-1px);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  }

  .action-btn:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .action-btn.primary {
    background: #1a1816;
    color: #f0ece7;
    border-color: transparent;
  }

  .action-btn.primary:hover {
    background: #2d2a26;
    color: white;
    box-shadow: 0 2px 16px rgba(0, 0, 0, 0.12);
  }

  .action-btn.danger {
    color: #c45450;
  }

  .action-btn.danger:hover {
    background: #fdf3f2;
    border-color: rgba(196, 84, 80, 0.15);
    color: #a03c38;
  }

  .action-btn.muted {
    color: #a09890;
  }

  .action-btn:disabled {
    opacity: 0.25;
    cursor: not-allowed;
    pointer-events: none;
  }

  .menu-wrapper {
    position: relative;
  }

  .menu-trigger {
    padding: 8px 10px;
    min-width: 36px;
    min-height: 36px;
    justify-content: center;
  }

  .menu-dropdown {
    position: absolute;
    bottom: calc(100% + 6px);
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
  }

  @keyframes menuIn {
    from { opacity: 0; transform: translateY(4px) scale(0.96); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .menu-divider {
    height: 1px;
    background: rgba(0, 0, 0, 0.06);
    margin: 2px 8px;
  }

  .menu-item {
    padding: 8px 12px;
    min-height: 36px;
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
    .version {
      color: #5a5450;
    }

    .name {
      color: #e8e0d8;
    }

    .status {
      color: #8a8078;
    }

    .status.alive {
      color: #8aae80;
    }

    .status.error {
      color: #e07070;
    }

    .action-btn {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.06);
      color: #b0a8a0;
    }

    .action-btn:hover {
      background: rgba(255, 255, 255, 0.14);
      border-color: rgba(255, 255, 255, 0.1);
      color: #e8e0d8;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
    }

    .action-btn.primary {
      background: #e8e0d8;
      color: #1c1b1a;
      border-color: transparent;
    }

    .action-btn.primary:hover {
      background: #f0ece7;
      color: #1c1b1a;
      box-shadow: 0 2px 16px rgba(0, 0, 0, 0.3);
    }

    .action-btn.danger {
      color: #e07070;
    }

    .action-btn.danger:hover {
      background: rgba(224, 112, 112, 0.12);
      border-color: rgba(224, 112, 112, 0.15);
      color: #f08080;
    }

    .action-btn.muted {
      color: #8a8078;
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

    .menu-divider {
      background: rgba(255, 255, 255, 0.06);
    }
  }
</style>
