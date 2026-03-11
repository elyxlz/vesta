<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { agent, agentName, agentState, resetReconnect } from "../lib/stores";
  import { setPort } from "../lib/ws";
  import { agentStatus, startAgent, stopAgent, restartAgent, deleteAgent, authenticate, backupAgent, restoreAgent } from "../lib/api";
  import { save, open } from "@tauri-apps/plugin-dialog";
  import type { AgentStatus } from "../lib/types";

  let {
    onChat,
    onConsole,
    onDestroyed,
    onReady,
  }: {
    onChat: () => void;
    onConsole: () => void;
    onDestroyed: () => void;
    onReady: (ready: boolean) => void;
  } = $props();

  let status = $state<AgentStatus>($agent?.status ?? "unknown");
  let authenticated = $state($agent?.authenticated ?? false);
  let agentReady = $state($agent?.agent_ready ?? false);
  let confirming = $state(false);
  let menuOpen = $state(false);
  let hovered = $state(false);
  let operation = $state<"idle" | "stopping" | "starting" | "authenticating" | "deleting" | "backing-up" | "restoring">("idle");
  let stopping = $derived(operation === "stopping");
  let starting = $derived(operation === "starting");
  let authenticating = $derived(operation === "authenticating");
  let deleting = $derived(operation === "deleting");
  let backingUp = $derived(operation === "backing-up");
  let restoring = $derived(operation === "restoring");
  let errorMsg = $state("");
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
      const info = await agentStatus();
      status = info.status;
      authenticated = info.authenticated;
      agentReady = info.agent_ready;
      agent.set(info);
      if (info.ws_port) setPort(info.ws_port);
      if (info.name) agentName.set(info.name);
      onReady(info.agent_ready);
      if (errorMsg) errorMsg = "";
    } catch {
      status = "unknown";
      authenticated = false;
      agentReady = false;
    }
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

  onMount(() => {
    refresh();
    poll = setInterval(refresh, 5000);
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);
  });

  onDestroy(() => {
    clearInterval(poll);
    if (leaveTimer) clearTimeout(leaveTimer);
    if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  });

  async function toggleRun() {
    if (busy) return;
    errorMsg = "";
    const wasStopping = running;
    operation = running ? "stopping" : "starting";
    try {
      if (wasStopping) {
        await stopAgent();
      } else {
        await startAgent();
        resetReconnect();
      }
      await syncStatus();
    } catch (e: any) {
      errorMsg = e?.message || (wasStopping ? "failed to stop" : "failed to start");
    } finally {
      operation = "idle";
    }
  }

  async function destroy() {
    if (!confirming) {
      confirming = true;
      return;
    }
    if (busy) return;
    errorMsg = "";
    operation = "deleting";
    try {
      await stopAgent().catch(() => {});
      await deleteAgent();
      onDestroyed();
    } catch (e: any) {
      errorMsg = e?.message || "failed to delete";
    } finally {
      operation = "idle";
      confirming = false;
    }
  }

  function cancelDestroy() {
    confirming = false;
  }

  async function handleAuth() {
    if (busy) return;
    errorMsg = "";
    operation = "authenticating";
    try {
      await authenticate();
      if (running) {
        await restartAgent();
      } else {
        await startAgent();
      }
      resetReconnect();
      await syncStatus();
    } catch (e: any) {
      errorMsg = e?.message || "sign in failed";
    } finally {
      operation = "idle";
    }
  }

  async function handleBackup() {
    if (busy) return;
    errorMsg = "";
    const path = await save({
      defaultPath: "vesta-backup.tar.gz",
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
    });
    if (!path) return;
    operation = "backing-up";
    try {
      await backupAgent(path);
    } catch (e: any) {
      errorMsg = e?.message || "backup failed";
    } finally {
      operation = "idle";
      await syncStatus();
    }
  }

  async function handleRestore() {
    if (busy) return;
    errorMsg = "";
    const path = await open({
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
      multiple: false,
      directory: false,
    });
    if (!path) return;
    operation = "restoring";
    try {
      await restoreAgent(path);
      resetReconnect();
    } catch (e: any) {
      errorMsg = e?.message || "restore failed";
    } finally {
      operation = "idle";
      await syncStatus();
    }
  }

  let busy = $derived(operation !== "idle");
  let running = $derived(status === "running");
  let dead = $derived(status === "dead");
  let alive = $derived(running && authenticated);
  let operational = $derived(alive && !deleting && !stopping);
  let fullyAlive = $derived(operational && agentReady);
  let showActions = $derived(hovered || !alive || confirming || menuOpen);

</script>

<div
  class="agent-view"
  role="group"
  aria-label="Controls"
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="creature-area"
    bind:this={creatureEl}
    onpointerenter={onOrbEnter}
    onpointerleave={onOrbLeave}
    onpointermove={onOrbMove}
  >
    <div class="orb-container" bind:this={orbEl} class:alive={fullyAlive} class:booting={operational && !agentReady} class:dead={(!alive && !starting && !authenticating) || deleting || dead} class:stopping class:starting class:authenticating class:deleting class:thinking={fullyAlive && $agentState === 'thinking'} class:tool-use={fullyAlive && $agentState === 'tool_use'}>
      <div class="orb-glow"></div>
      <div class="orb-body">
        <div class="orb-highlight"></div>
      </div>
      <div class="orb-ring"></div>
      <div class="orb-ambient"></div>
    </div>

    <div class="label">
      <span class="name">{$agentName}</span>
      <span class="status" class:alive={fullyAlive} class:error={!!errorMsg} title={errorMsg || ""}>
        {errorMsg ? errorMsg : deleting ? "deleting..." : stopping ? "stopping..." : starting ? "starting..." : authenticating ? "signing in..." : backingUp ? "backing up..." : restoring ? "restoring..." : fullyAlive ? "alive" : operational ? "waking up..." : running ? "not signed in" : dead ? "broken — delete and recreate" : "stopped"}
      </span>
    </div>

    <div class="actions" class:visible={showActions && !deleting && !stopping && !starting && !authenticating && !backingUp && !restoring} inert={!showActions || deleting || stopping || starting || authenticating || backingUp || restoring}>
      {#if confirming}
        <button class="action-btn danger" disabled={busy} onclick={destroy}>confirm</button>
        <button class="action-btn muted" disabled={busy} onclick={cancelDestroy}>cancel</button>
      {:else}
        {#if alive}
          <button class="action-btn primary" onclick={onChat} data-tip="open chat">chat</button>
        {:else if running && !authenticated}
          <button class="action-btn primary" disabled={busy} onclick={handleAuth} data-tip="sign in to claude">sign in</button>
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
              <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleBackup(); }} data-tip="save backup to file">{backingUp ? "backing up..." : "backup"}</button>
              <button class="menu-item" disabled={busy} onclick={() => { menuOpen = false; handleRestore(); }} data-tip="restore from backup file">{restoring ? "restoring..." : "restore"}</button>
              <button class="menu-item danger" disabled={busy} onclick={() => { menuOpen = false; destroy(); }} data-tip="permanently delete">delete</button>
            </div>
          {/if}
        </div>
      {/if}
    </div>
  </div>


</div>

<style>
  .agent-view {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    animation: viewIn 0.6s var(--spring);
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
    padding: min(120px, 15vh) min(180px, 20vw);
  }

  /* --- Orb --- */
  .orb-container {
    position: relative;
    width: 140px;
    height: 140px;
    will-change: transform;
    transition: filter 0.8s var(--spring);
  }

  .orb-body {
    position: absolute;
    inset: 20px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, #b8ceb0, #7a9e70 50%, #5a7e50);
    box-shadow:
      inset 0 -8px 20px rgba(0, 0, 0, 0.15),
      inset 0 4px 12px rgba(255, 255, 255, 0.15);
    transition: background 0.8s var(--spring), box-shadow 0.8s var(--spring), transform 0.8s var(--spring);
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
    background: radial-gradient(circle, rgba(138, 180, 120, 0.35), transparent 70%);
    filter: blur(18px);
    transition: opacity 0.8s var(--spring), background 0.8s var(--spring);
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
    background: radial-gradient(circle, rgba(138, 180, 120, 0.08), transparent 70%);
    transition: opacity 0.8s var(--spring), background 0.8s var(--spring);
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
    animation: float 2s ease-in-out infinite;
  }

  .orb-container.thinking .orb-body,
  .orb-container.tool-use .orb-body {
    background: radial-gradient(circle at 38% 32%, #e8d0a0, #c4a060 50%, #a08040);
    animation: orb-breathe 1.2s ease-in-out infinite;
  }

  .orb-container.thinking .orb-glow,
  .orb-container.tool-use .orb-glow {
    background: radial-gradient(circle, rgba(200, 170, 100, 0.4), transparent 70%);
    animation: glow-pulse 1.2s ease-in-out infinite;
  }

  .orb-container.thinking .orb-ambient,
  .orb-container.tool-use .orb-ambient {
    background: radial-gradient(circle, rgba(200, 170, 100, 0.12), transparent 70%);
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

  .orb-container.booting .orb-body {
    background: radial-gradient(circle at 38% 32%, #c4deb8, #8ab880 50%, #6a9e5a);
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .orb-container.booting .orb-glow {
    animation: glow-swell 1.5s ease-in-out infinite;
  }

  /* Authenticating state — slow pulse, waiting on user */
  .orb-container.authenticating .orb-body {
    background: radial-gradient(circle at 38% 32%, #c0d0e8, #80a0c4 50%, #6080a4);
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .orb-container.authenticating .orb-glow {
    background: radial-gradient(circle, rgba(100, 150, 200, 0.35), transparent 70%);
    animation: glow-pulse 2s ease-in-out infinite;
  }

  .orb-container.authenticating .orb-ambient {
    background: radial-gradient(circle, rgba(100, 150, 200, 0.1), transparent 70%);
  }

  .orb-container.authenticating {
    animation: float 3s ease-in-out infinite;
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
  .orb-container.dead .orb-body {
    background: radial-gradient(circle at 38% 32%, #c4bdb5, #a09890 50%, #8b7e74);
    box-shadow:
      inset 0 -8px 20px rgba(0, 0, 0, 0.1),
      inset 0 4px 12px rgba(255, 255, 255, 0.05);
    transform: scale(0.92);
  }

  .orb-container.dead .orb-glow {
    opacity: 0.15;
    background: radial-gradient(circle, rgba(160, 152, 144, 0.2), transparent 70%);
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
    transition: all 0.2s var(--spring-bouncy);
    letter-spacing: 0.01em;
  }

  .action-btn:hover {
    background: white;
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

  .menu-item {
    padding: 8px 12px;
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

  @media (prefers-color-scheme: dark) {
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
  }
</style>
