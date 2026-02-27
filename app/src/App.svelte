<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { get } from "svelte/store";
  import { agent, agentName } from "./lib/stores";
  import { agentExists, agentStatus } from "./lib/api";
  import Onboarding from "./components/Onboarding.svelte";
  import AgentView from "./components/AgentView.svelte";
  import Console from "./components/Console.svelte";

  let view = $state<"loading" | "onboarding" | "home" | "console">("loading");
  let ready = $state(false);

  const appWindow = getCurrentWindow();

  onMount(async () => {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const exists = await agentExists();
      if (exists) {
        const info = await agentStatus();
        agent.set(info);
        view = "home";
      } else {
        view = "onboarding";
      }
    } catch {
      view = "onboarding";
    }
    ready = true;
  });

  function handleOnboardingComplete(name: string) {
    agentName.set(name);
    view = "home";
  }

  function handleDestroyed() {
    agent.set(null);
    view = "onboarding";
  }

  let isDark = $derived(view === "console");

  function startDrag(e: MouseEvent) {
    if ((e.target as HTMLElement).closest(".window-controls")) return;
    appWindow.startDragging();
  }
</script>

<div class="window" class:dark={isDark}>
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

  <main class:ready>
    {#if view === "loading"}
      <div class="loading">
        <div class="logo-mark">v</div>
      </div>
    {:else if view === "onboarding"}
      <Onboarding onComplete={handleOnboardingComplete} />
    {:else if view === "home"}
      <AgentView
        onConsole={() => (view = "console")}
        onDestroyed={handleDestroyed}
      />
    {:else if view === "console"}
      <Console
        name={get(agentName)}
        onBack={() => (view = "home")}
      />
    {/if}
  </main>
</div>

<style>
  :global(*) {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
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

  .window {
    height: 100vh;
    display: flex;
    flex-direction: column;
    background: #f8f6f3;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid rgba(0, 0, 0, 0.08);
    box-shadow:
      0 0 0 0.5px rgba(0, 0, 0, 0.06),
      0 8px 40px rgba(0, 0, 0, 0.08),
      0 2px 12px rgba(0, 0, 0, 0.04);
  }

  .window.dark {
    background: #111110;
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
    padding: 0 14px;
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
    gap: 7px;
  }

  .wc {
    width: 13px;
    height: 13px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
    padding: 0;
    color: transparent;
  }

  .wc.close {
    background: #ff5f57;
  }

  .wc.minimize {
    background: #febc2e;
  }

  .wc:hover {
    color: rgba(0, 0, 0, 0.5);
  }

  .wc:active {
    filter: brightness(0.85);
  }

  main {
    flex: 1;
    display: flex;
    opacity: 0;
    transition: opacity 0.5s ease;
    min-height: 0;
  }

  main.ready {
    opacity: 1;
  }

  .loading {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
  }

  .logo-mark {
    font-size: 32px;
    font-weight: 300;
    color: #b5aba1;
    letter-spacing: -2px;
    animation: breathe 2.5s ease-in-out infinite;
  }

  @keyframes breathe {
    0%, 100% { opacity: 0.3; transform: scale(1); }
    50% { opacity: 0.8; transform: scale(1.03); }
  }
</style>
