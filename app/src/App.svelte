<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { isTauri } from "./lib/env";
  import { isConnected, getConnection, clearConnection } from "./lib/connection";
  import { autoSetup, listAgents, checkAndInstallUpdate, runInstallScript } from "./lib/api";
  import { createAgentConnection, type AgentConnection } from "./lib/ws";
  import { removeAgentState } from "./lib/store.svelte";
  import { detectPlatform } from "./lib/platform";
  import Onboarding from "./components/Onboarding.svelte";
  import AgentView from "./components/AgentView.svelte";
  import Chat from "./components/Chat.svelte";
  import Console from "./components/Console.svelte";
  import GridView from "./components/GridView.svelte";

  const platform = detectPlatform();

  type View = "loading" | "connect" | "grid" | "onboarding" | "agent-home" | "agent-chat" | "agent-console";

  let view = $state<View>("loading");
  let ready = $state(false);
  let transitioning = $state(false);
  let selectedAgent = $state<{ name: string; wsPort: number } | null>(null);
  let agentConnection = $state<AgentConnection | null>(null);
  let onboardingInitialName = $state("");
  let hasAgents = $state(false);
  let updateInfo = $state<{ version: string; installing: boolean } | null>(null);
  let connected = $state(false);

  async function setView(next: View) {
    if (next === view) return;
    transitioning = true;
    await new Promise((r) => setTimeout(r, 150));
    view = next;
    transitioning = false;
  }

  let connectionHost = $derived(() => {
    const conn = getConnection();
    if (!conn) return "";
    try { return new URL(conn.url).hostname; } catch { return conn.url; }
  });

  const SCREEN_FRACTION = 0.6;
  const MIN_SIZE = 400;
  const MAX_SIZE = 800;

  async function scaleToMonitor() {
    if (!isTauri) return;
    const { getCurrentWindow, LogicalSize } = await import("@tauri-apps/api/window");
    const appWindow = getCurrentWindow();
    const shortest = Math.min(window.screen.width, window.screen.height);
    const size = Math.round(Math.max(MIN_SIZE, Math.min(MAX_SIZE, shortest * SCREEN_FRACTION)));
    await appWindow.setSize(new LogicalSize(size, size));
    await appWindow.center();
  }

  async function loadAgents() {
    const agents = await listAgents().catch(() => null);
    try {
      if (!agents) throw new Error();
      hasAgents = agents.length > 0;
      if (agents.length === 1 && agents[0].authenticated) {
        selectedAgent = { name: agents[0].name, wsPort: agents[0].ws_port };
        agentConnection = createAgentConnection(agents[0].name);
        agentConnection.connect();
        view = "agent-home";
      } else if (agents.length > 1) {
        view = "grid";
      } else if (agents.length === 1 && !agents[0].authenticated) {
        onboardingInitialName = agents[0].name;
        view = "onboarding";
      } else {
        view = "onboarding";
      }
    } catch {
      view = "onboarding";
    }
  }

  onMount(async () => {
    await Promise.all([
      autoSetup().catch((e: unknown) => console.warn("auto-setup failed:", e)),
      scaleToMonitor(),
      new Promise((r) => setTimeout(r, 400)),
    ]);

    if (!isConnected()) {
      view = "connect";
      ready = true;
      return;
    }

    connected = true;
    await loadAgents();
    checkAndInstallUpdate().then((result) => {
      if (result) updateInfo = { version: result.version, installing: result.installing };
    });
    ready = true;
  });

  function clearAgentConnection() {
    agentConnection?.disconnect();
    agentConnection = null;
    selectedAgent = null;
  }

  onDestroy(clearAgentConnection);

  function handleDisconnect() {
    clearAgentConnection();
    clearConnection();
    connected = false;
    hasAgents = false;
    view = "connect";
  }

  function handleSelectAgent(name: string, wsPort: number) {
    agentConnection?.disconnect();
    selectedAgent = { name, wsPort };
    agentConnection = createAgentConnection(name);
    agentConnection.connect();
    setView("agent-home");
  }

  function handleBackToGrid() {
    clearAgentConnection();
    setView("grid");
  }

  async function handleDestroyed() {
    if (selectedAgent) removeAgentState(selectedAgent.name);
    clearAgentConnection();
    const remaining = await listAgents().catch(() => []);
    if (remaining.length === 0) {
      hasAgents = false;
      view = "onboarding";
    } else {
      view = "grid";
    }
  }

  async function handleConnected(_name: string) {
    connected = true;
    await loadAgents();
    ready = true;
  }

  async function handleOnboardingComplete(name: string) {
    hasAgents = true;
    onboardingInitialName = "";
    const agents = await listAgents().catch(() => []);
    const agent = agents.find((b) => b.name === name);
    if (agent) {
      agentConnection?.disconnect();
      selectedAgent = { name: agent.name, wsPort: agent.ws_port };
      agentConnection = createAgentConnection(agent.name);
      agentConnection.connect();
      await setView("agent-chat");
    } else {
      await setView("grid");
    }
  }

  let isDark = $derived(view === "agent-console" || view === "agent-chat");

  let tipText = $state("");
  let tipX = $state(0);
  let tipY = $state(0);
  let rafPending = false;

  function onGlobalMove(e: PointerEvent) {
    const target = (e.target as HTMLElement)?.closest?.("[data-tip]") as HTMLElement | null;
    const tip = target?.dataset.tip ?? "";
    if (tip !== tipText) tipText = tip;
    if (!tip || rafPending) return;
    rafPending = true;
    const x = e.clientX;
    const y = e.clientY;
    requestAnimationFrame(() => {
      tipX = x;
      tipY = y;
      rafPending = false;
    });
  }

  async function startDrag(e: MouseEvent) {
    if (!isTauri) return;
    if ((e.target as HTMLElement).closest(".window-controls")) return;
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    getCurrentWindow().startDragging();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="window" class:dark={isDark} onpointermove={onGlobalMove}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="titlebar" class:titlebar-macos={isTauri && platform === "macos"} class:titlebar-right={!isTauri || platform !== "macos"} onmousedown={startDrag}>
    {#if connected}
      <div class="conn-status">
        <span class="conn-dot"></span>
        <span class="conn-label">{connectionHost()}</span>
        <button class="conn-logout" onclick={handleDisconnect} data-tip="disconnect">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
            <polyline points="16 17 21 12 16 7"/>
            <line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </button>
      </div>
    {/if}
    {#if isTauri && platform !== "macos"}
      <div class="window-controls {platform}">
        <button class="wc" onclick={async () => { const { getCurrentWindow } = await import("@tauri-apps/api/window"); getCurrentWindow().minimize(); }} aria-label="minimize">
          <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 5h6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        </button>
        <button class="wc close" onclick={async () => { const { getCurrentWindow } = await import("@tauri-apps/api/window"); getCurrentWindow().close(); }} aria-label="close">
          <svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
        </button>
      </div>
    {/if}
  </div>

  <main class:ready class:transitioning inert={transitioning}>
    {#if view === "loading"}
      <div class="loading">
        <div class="logo-mark">v</div>
        <span class="loading-label">loading...</span>
      </div>
    {:else if view === "connect"}
      <Onboarding onComplete={handleConnected} serverConfigured={false} initialStep="connect" />
    {:else if view === "grid"}
      <GridView
        onSelect={handleSelectAgent}
        onCreate={() => { onboardingInitialName = ""; setView("onboarding"); }}
        onChat={(name, wsPort) => { handleSelectAgent(name, wsPort); setView("agent-chat"); }}
        onConsole={(name, wsPort) => { handleSelectAgent(name, wsPort); setView("agent-console"); }}
      />
    {:else if view === "onboarding"}
      <Onboarding onComplete={handleOnboardingComplete} onCancel={hasAgents ? () => setView("grid") : undefined} initialName={onboardingInitialName} serverConfigured={hasAgents} />
    {:else if (view === "agent-home" || view === "agent-chat" || view === "agent-console") && selectedAgent && agentConnection}
      <div class="agent-stack">
        <div class="agent-layer" class:agent-hidden={view !== "agent-home"} inert={view !== "agent-home"}>
          <AgentView
            name={selectedAgent.name}
            connection={agentConnection}
            onChat={() => setView("agent-chat")}
            onConsole={() => setView("agent-console")}
            onDestroyed={handleDestroyed}
            onBack={handleBackToGrid}
          />
        </div>
        {#if view === "agent-chat"}
          <div class="overlay-layer">
            <Chat name={selectedAgent.name} connection={agentConnection} onBack={() => setView("agent-home")} />
          </div>
        {:else if view === "agent-console"}
          <div class="overlay-layer">
            <Console name={selectedAgent.name} onBack={() => setView("agent-home")} />
          </div>
        {/if}
      </div>
    {/if}
  </main>

  {#if isTauri && updateInfo && (view === "agent-home" || view === "grid")}
    <div class="update-bar">
      {#if updateInfo.installing}
        v{updateInfo.version} installed — restart to apply
      {:else}
        v{updateInfo.version} available —
        <button class="update-dismiss" onclick={() => { const v = updateInfo!.version; updateInfo = { version: v, installing: true }; runInstallScript(v).catch(() => { updateInfo = null }) }}>install</button>
      {/if}
      <button class="update-dismiss" onclick={() => updateInfo = null}>dismiss</button>
    </div>
  {/if}

  <div class="tooltip" class:visible={!!tipText} style="left: clamp(40px, {tipX}px, calc(100vw - 40px)); top: clamp(28px, {tipY}px, calc(100vh - 20px));">{tipText}</div>
</div>

<style>
  :global(*) {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
  }

  :root {
    --spring: cubic-bezier(0.16, 1, 0.3, 1);
    --spring-bouncy: cubic-bezier(0.34, 1.56, 0.64, 1);
    --spring-snappy: cubic-bezier(0.2, 0, 0, 1);
  }

  @supports (animation-timing-function: linear(0, 1)) {
    :root {
      --spring: linear(
        0, 0.009, 0.035 2.1%, 0.141, 0.281 6.7%, 0.723 12.9%,
        0.938 16.7%, 1.017, 1.041, 1.043 24.4%, 1.012 27.4%,
        1.004, 1.001 32%, 0.999 37.7%, 1
      );
      --spring-bouncy: linear(
        0, 0.004, 0.016, 0.035, 0.063, 0.098, 0.141 9.1%,
        0.25, 0.391, 0.563, 0.765, 1.006 45.2%,
        1.071, 1.088 57.6%, 1.06, 1.019, 0.995 72.9%,
        0.986, 0.989 83%, 1.001, 1.006 91.9%, 1
      );
      --spring-snappy: linear(
        0, 0.11 2.6%, 0.424 7.2%, 0.766 12.6%,
        0.946 17.5%, 1.018 22.4%, 1.026 27.4%,
        1.008 35%, 1.001 43%, 1
      );
    }
  }

  :global(html) {
    background: transparent;
  }

  :global(body) {
    font-family: "Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    background: transparent;
    color: #1a1816;
    overflow: hidden;
    height: 100vh;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  :global(::selection) {
    background: rgba(139, 126, 116, 0.25);
  }

  :global(:focus-visible) {
    outline: none;
  }

  :global(button:focus-visible),
  :global(textarea:focus-visible),
  :global(input:focus-visible) {
    box-shadow: 0 0 0 3px rgba(139, 126, 116, 0.2) !important;
  }

  @media (prefers-color-scheme: dark) {
    :global(button:focus-visible),
    :global(textarea:focus-visible),
    :global(input:focus-visible) {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.1) !important;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.orb-container.alive),
    :global(.orb-container.thinking),
    :global(.orb-container.tool-use),
    :global(.orb-container.booting),
    :global(.orb-container.authenticating),
    :global(.orb-container.alive .orb-glow),
    :global(.orb-container.thinking .orb-glow),
    :global(.orb-container.tool-use .orb-glow),
    :global(.orb-container.booting .orb-glow),
    :global(.orb-container.authenticating .orb-glow),
    :global(.orb-container.alive .orb-body),
    :global(.orb-container.thinking .orb-body),
    :global(.orb-container.tool-use .orb-body),
    :global(.orb-container.booting .orb-body),
    :global(.orb-container.authenticating .orb-body),
    :global(.orb-container.stopping .orb-body),
    :global(.orb-container.stopping .orb-glow),
    :global(.orb-container.stopping .orb-ring),
    :global(.orb-container.deleting),
    :global(.orb-container.deleting .orb-glow),
    :global(.logo-mark),
    :global(.empty-dots span),
    :global(.thinking-indicator span),
    :global(.line),
    :global(.fill),
    :global(.done-icon),
    :global(.platform-icon) {
      animation: none !important;
    }
    :global(.orb-container.alive .orb-glow) { opacity: 1; }
    :global(.logo-mark) { opacity: 0.6; }
    :global(.empty-dots span) { opacity: 0.5; }
    :global(.thinking-indicator span) { opacity: 0.5; }
    :global(.actions) { transition: opacity 0.01ms !important; transform: none !important; }
    :global(.actions.visible) { transform: none !important; }
    :global(.step-anim) { animation: none !important; }
    :global(.panel) { animation: none !important; }
    :global(.agent-view) { animation: none !important; }
    :global(.grid-view) { animation: none !important; }
    :global(.menu-dropdown) { animation: none !important; }
    :global(.msg) { animation: none !important; }
    :global(.status.error) { animation: none !important; }
    :global(.error) { animation: none !important; }
  }

  .window {
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: rgba(248, 246, 243, 0.96);
    border-radius: 12px;
    corner-shape: squircle;
    overflow: hidden;
    border: 1px solid rgba(0, 0, 0, 0.08);
    transition: background 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
    box-shadow:
      0 0 0 0.5px rgba(0, 0, 0, 0.06),
      0 8px 40px rgba(0, 0, 0, 0.08),
      0 2px 12px rgba(0, 0, 0, 0.04);
  }

  .window.dark {
    background: rgba(17, 17, 16, 0.96);
    border-color: rgba(255, 255, 255, 0.06);
    box-shadow:
      0 0 0 0.5px rgba(255, 255, 255, 0.04),
      0 8px 40px rgba(0, 0, 0, 0.3),
      0 2px 12px rgba(0, 0, 0, 0.2);
  }

  .titlebar {
    height: 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 16px;
    flex-shrink: 0;
    cursor: grab;
    position: relative;
    z-index: 100;
  }

  .titlebar.titlebar-macos {
    padding-left: 78px;
  }

  .titlebar.titlebar-right {
    justify-content: flex-end;
  }

  .titlebar:active {
    cursor: grabbing;
  }

  .conn-status {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-left: 8px;
    font-size: 11px;
    font-weight: 450;
    color: #8a8078;
    letter-spacing: 0.01em;
    user-select: none;
  }

  .conn-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #6abf69;
    flex-shrink: 0;
  }

  .conn-label {
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .conn-logout {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 22px;
    height: 22px;
    border-radius: 4px;
    border: none;
    background: transparent;
    color: #9a928a;
    cursor: pointer;
    padding: 0;
    transition: all 0.15s ease;
  }

  .conn-logout:hover {
    background: rgba(0, 0, 0, 0.06);
    color: #c45450;
  }

  /* --- Linux: flat icon buttons --- */
  .window-controls.linux {
    display: flex;
    gap: 2px;
  }

  .linux .wc {
    width: 28px;
    height: 28px;
    border-radius: 6px;
    corner-shape: squircle;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
    padding: 0;
    color: rgba(0, 0, 0, 0.35);
    background: transparent;
  }

  .linux .wc:hover {
    background: rgba(0, 0, 0, 0.06);
    color: rgba(0, 0, 0, 0.6);
  }

  .linux .wc.close:hover {
    background: rgba(224, 80, 70, 0.12);
    color: #c45450;
  }

  .linux .wc:active {
    transform: scale(0.9);
  }

  /* --- Windows: caption-style buttons --- */
  .window-controls.windows {
    display: flex;
    gap: 0;
    margin-right: -16px;
  }

  .windows .wc {
    width: 46px;
    height: 40px;
    border-radius: 0;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: background 0.1s ease;
    padding: 0;
    color: rgba(0, 0, 0, 0.6);
    background: transparent;
  }

  .windows .wc:hover {
    background: rgba(0, 0, 0, 0.06);
  }

  .windows .wc.close:hover {
    background: #c42b1c;
    color: white;
  }

  .windows .wc:active {
    background: rgba(0, 0, 0, 0.1);
  }

  .windows .wc.close:active {
    background: #b02818;
    color: white;
  }

  main {
    flex: 1;
    display: flex;
    flex-direction: column;
    opacity: 0;
    transition: opacity 0.25s ease;
    min-height: 0;
  }

  main > :global(*) {
    flex: 1;
    min-height: 0;
  }

  .agent-stack {
    position: relative;
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  .agent-layer {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
  }

  .agent-layer.agent-hidden {
    visibility: hidden;
    pointer-events: none;
  }

  .overlay-layer {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
  }

  main.ready {
    opacity: 1;
  }

  main.transitioning {
    opacity: 0;
    transition: opacity 0.15s ease;
  }

  .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    user-select: none;
  }

  .logo-mark {
    font-size: 32px;
    font-weight: 300;
    color: #b5aba1;
    letter-spacing: -2px;
    animation: breathe 2.5s ease-in-out infinite;
  }

  .loading-label {
    font-size: 11px;
    font-weight: 400;
    color: #b5aba1;
    opacity: 0.5;
    margin-top: 12px;
    letter-spacing: 0.04em;
  }

  @keyframes breathe {
    0%, 100% { opacity: 0.3; transform: scale(1); }
    50% { opacity: 0.8; transform: scale(1.03); }
  }

  .tooltip {
    position: fixed;
    transform: translate(-50%, -100%) translateY(-8px);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 11px;
    font-weight: 450;
    color: rgba(255, 255, 255, 0.85);
    background: rgba(30, 28, 26, 0.85);
    backdrop-filter: blur(8px);
    pointer-events: none;
    white-space: nowrap;
    letter-spacing: 0.02em;
    z-index: 200;
    opacity: 0;
    transition: opacity 0.12s ease, transform 0.12s ease;
  }

  .tooltip.visible {
    opacity: 1;
    transform: translate(-50%, -100%) translateY(-12px);
  }

  :global(.line a) {
    color: rgba(130, 180, 255, 0.9);
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
  }

  :global(.line a:hover) {
    color: rgba(160, 200, 255, 1);
  }

  :global(.line strong) {
    font-weight: 600;
    color: inherit;
  }

  :global(.line code) {
    background: rgba(255, 255, 255, 0.08);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 0.95em;
  }

  @media (prefers-color-scheme: dark) {
    .window:not(.dark) {
      background: rgba(28, 27, 26, 0.96);
      border-color: rgba(255, 255, 255, 0.06);
      box-shadow:
        0 0 0 0.5px rgba(255, 255, 255, 0.04),
        0 8px 40px rgba(0, 0, 0, 0.3),
        0 2px 12px rgba(0, 0, 0, 0.2);
    }

    :global(body) {
      color: #e8e0d8;
    }

    :global(::selection) {
      background: rgba(139, 126, 116, 0.4);
    }

    .logo-mark {
      color: #8a8078;
    }

    .loading-label {
      color: #6a625a;
    }

    .conn-status {
      color: #6a625a;
    }

    .conn-logout:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #e07070;
    }

    .linux .wc {
      color: rgba(255, 255, 255, 0.35);
    }

    .linux .wc:hover {
      background: rgba(255, 255, 255, 0.08);
      color: rgba(255, 255, 255, 0.7);
    }

    .linux .wc.close:hover {
      background: rgba(224, 80, 70, 0.2);
      color: #e07070;
    }

    .windows .wc {
      color: rgba(255, 255, 255, 0.7);
    }

    .windows .wc:hover {
      background: rgba(255, 255, 255, 0.08);
    }

    .windows .wc.close:hover {
      background: #c42b1c;
      color: white;
    }

    .windows .wc:active {
      background: rgba(255, 255, 255, 0.12);
    }

    .windows .wc.close:active {
      background: #b02818;
      color: white;
    }
  }

  .update-bar {
    position: absolute;
    bottom: 28px;
    left: 50%;
    transform: translateX(-50%);
    padding: 4px 14px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 450;
    color: #7a726a;
    background: rgba(0, 0, 0, 0.05);
    border: 1px solid rgba(0, 0, 0, 0.06);
    display: flex;
    align-items: center;
    gap: 10px;
    z-index: 50;
    animation: fadeSlideUp 0.3s var(--spring);
    letter-spacing: 0.01em;
  }

  .update-dismiss {
    background: none;
    border: none;
    color: #9a928a;
    font-size: 10px;
    cursor: pointer;
    padding: 0;
    font-family: inherit;
  }

  .update-dismiss:hover {
    color: #5a524a;
  }

  @keyframes fadeSlideUp {
    from { opacity: 0; transform: translateX(-50%) translateY(6px); }
    to { opacity: 1; transform: translateX(-50%); }
  }

  @media (prefers-color-scheme: dark) {
    .update-bar {
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.08);
      color: #8a8078;
    }

    .update-dismiss {
      color: #6a625a;
    }

    .update-dismiss:hover {
      color: #a09890;
    }
  }
</style>
