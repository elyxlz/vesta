<script lang="ts">
  import { onMount } from "svelte";
  import { getCurrentWindow } from "@tauri-apps/api/window";
  import { agent, agentName } from "./lib/stores";
  import { agentStatus } from "./lib/api";
  import Onboarding from "./components/Onboarding.svelte";
  import AgentView from "./components/AgentView.svelte";
  import Console from "./components/Console.svelte";

  let view = $state<"loading" | "onboarding" | "home" | "console">("loading");
  let ready = $state(false);

  const appWindow = getCurrentWindow();

  onMount(async () => {
    await new Promise((r) => setTimeout(r, 400));
    try {
      const info = await agentStatus();
      if (info.status === "NotFound") {
        view = "onboarding";
      } else {
        agent.set(info);
        view = "home";
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
        name={$agentName}
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

  :root {
    --spring: cubic-bezier(0.16, 1, 0.3, 1);
    --spring-bouncy: cubic-bezier(0.34, 1.56, 0.64, 1);
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
    }
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
    outline: 2px solid rgba(139, 126, 116, 0.4);
    outline-offset: 2px;
  }

  .window.dark :global(:focus-visible) {
    outline-color: rgba(255, 255, 255, 0.25);
  }

  @media (prefers-reduced-motion: reduce) {
    :global(.orb-container.alive),
    :global(.orb-container.alive .orb-glow),
    :global(.orb-container.alive .orb-body),
    :global(.logo-mark),
    :global(.empty-dots span),
    :global(.line),
    :global(.fill) {
      animation: none !important;
    }
    :global(.orb-container.alive .orb-glow) { opacity: 1; }
    :global(.logo-mark) { opacity: 0.6; }
    :global(.empty-dots span) { opacity: 0.5; }
    :global(.actions) { transition: opacity 0.01ms !important; transform: none !important; }
    :global(.actions.visible) { transform: none !important; }
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
    gap: 8px;
  }

  .wc {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    border: none;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
    padding: 0;
    color: transparent;
  }

  .wc.close {
    background: #ed6a5f;
  }

  .wc.minimize {
    background: #f6be50;
  }

  .wc:hover {
    color: rgba(0, 0, 0, 0.5);
  }

  .wc:active {
    transform: scale(0.85);
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

    .logo-mark {
      color: #8a8078;
    }
  }
</style>
