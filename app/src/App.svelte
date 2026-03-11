<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { listAgents } from "./lib/api";
  import { createAgentConnection, type AgentConnection } from "./lib/ws";
  import Onboarding from "./components/Onboarding.svelte";
  import AgentView from "./components/AgentView.svelte";
  import Chat from "./components/Chat.svelte";
  import Console from "./components/Console.svelte";
  import GridView from "./components/GridView.svelte";

  type View = "loading" | "grid" | "onboarding" | "agent-home" | "agent-chat" | "agent-console";

  let view = $state<View>("loading");
  let ready = $state(false);
  let transitioning = $state(false);
  let selectedAgent = $state<{ name: string; wsPort: number } | null>(null);
  let agentConnection = $state<AgentConnection | null>(null);
  let hasAgents = $state(false);

  async function setView(next: View) {
    if (next === view) return;
    transitioning = true;
    await new Promise((r) => setTimeout(r, 150));
    view = next;
    transitioning = false;
  }

  const appWindow = getCurrentWindow();

  onMount(async () => {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const agents = await listAgents();
      hasAgents = agents.length > 0;
      if (hasAgents) {
        view = "grid";
      } else {
        view = "onboarding";
      }
    } catch {
      view = "onboarding";
    }
    ready = true;
  });

  function clearConnection() {
    agentConnection?.disconnect();
    agentConnection = null;
    selectedAgent = null;
  }

  onDestroy(clearConnection);

  function handleSelectAgent(name: string, wsPort: number) {
    agentConnection?.disconnect();
    selectedAgent = { name, wsPort };
    agentConnection = createAgentConnection(wsPort);
    agentConnection.connect();
    setView("agent-home");
  }

  function handleBackToGrid() {
    clearConnection();
    setView("grid");
  }

  function handleDestroyed() {
    clearConnection();
    setView("grid");
  }

  function handleOnboardingComplete(_name: string) {
    setView("grid");
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

  function startDrag(e: MouseEvent) {
    if ((e.target as HTMLElement).closest(".window-controls")) return;
    appWindow.startDragging();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="window" class:dark={isDark} onpointermove={onGlobalMove}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="titlebar" onmousedown={startDrag}>
    <div class="window-controls">
      <button class="wc close" onclick={() => appWindow.close()} aria-label="close">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
      </button>
      <button class="wc minimize" onclick={() => appWindow.minimize()} aria-label="minimize">
        <svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 5h6" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>

  <main class:ready class:transitioning inert={transitioning}>
    {#if view === "loading"}
      <div class="loading">
        <div class="logo-mark">v</div>
        <span class="loading-label">loading...</span>
      </div>
    {:else if view === "grid"}
      <GridView
        onSelect={handleSelectAgent}
        onCreate={() => setView("onboarding")}
        onChat={(name, wsPort) => { handleSelectAgent(name, wsPort); setView("agent-chat"); }}
        onConsole={(name, wsPort) => { handleSelectAgent(name, wsPort); setView("agent-console"); }}
      />
    {:else if view === "onboarding"}
      <Onboarding onComplete={handleOnboardingComplete} onCancel={hasAgents ? () => setView("grid") : undefined} />
    {:else if view === "agent-home" && selectedAgent && agentConnection}
      <AgentView
        name={selectedAgent.name}
        connection={agentConnection}
        onChat={() => setView("agent-chat")}
        onConsole={() => setView("agent-console")}
        onDestroyed={handleDestroyed}
        onBack={handleBackToGrid}
      />
    {:else if view === "agent-chat" && selectedAgent && agentConnection}
      <Chat
        name={selectedAgent.name}
        connection={agentConnection}
        onBack={() => setView("agent-home")}
      />
    {:else if view === "agent-console" && selectedAgent}
      <Console
        name={selectedAgent.name}
        onBack={() => setView("agent-home")}
      />
    {/if}
  </main>

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
    padding: 0 16px;
    flex-shrink: 0;
    cursor: grab;
    position: relative;
    z-index: 100;
  }

  .titlebar:active {
    cursor: grabbing;
  }

  .window-controls {
    display: flex;
    gap: 0;
    margin-left: -8px;
  }

  .wc {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
    padding: 0;
    color: transparent;
    background: transparent;
    position: relative;
  }

  .wc::after {
    content: "";
    width: 12px;
    height: 12px;
    border-radius: 50%;
    position: absolute;
  }

  .wc.close::after {
    background: #ed6a5f;
  }

  .wc.minimize::after {
    background: #f6be50;
  }

  .wc svg {
    position: relative;
    z-index: 1;
  }

  .window-controls:hover .wc {
    color: rgba(0, 0, 0, 0.5);
  }

  .wc:active {
    transform: scale(0.85);
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
    color: rgba(255, 255, 255, 0.9);
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
  }
</style>
