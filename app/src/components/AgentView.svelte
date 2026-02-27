<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { agent, agentName } from "../lib/stores";
  import { agentStatus, startAgent, stopAgent, deleteAgent } from "../lib/api";
  import type { AgentStatus } from "../lib/types";
  import { get } from "svelte/store";

  let {
    onConsole,
    onDestroyed,
  }: {
    onConsole: () => void;
    onDestroyed: () => void;
  } = $props();

  let displayName = $state(get(agentName));

  let status = $state<AgentStatus>("Unknown");
  let hovered = $state(false);
  let confirming = $state(false);
  let poll: ReturnType<typeof setInterval>;

  async function refresh() {
    try {
      const info = await agentStatus();
      status = info.status;
      agent.set(info);
    } catch {
      status = "Unknown";
    }
  }

  onMount(() => {
    refresh();
    poll = setInterval(refresh, 3000);
  });

  onDestroy(() => clearInterval(poll));

  async function toggleRun() {
    try {
      if (status === "Running") {
        await stopAgent();
      } else {
        await startAgent();
      }
      await refresh();
    } catch {}
  }

  async function destroy() {
    if (!confirming) {
      confirming = true;
      return;
    }
    try {
      await stopAgent().catch(() => {});
      await deleteAgent();
      onDestroyed();
    } catch {}
  }

  function cancelDestroy() {
    confirming = false;
  }

  let alive = $derived(status === "Running");
  let restarting = $derived(status === "Restarting");
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="agent-view"
  onmouseenter={() => (hovered = true)}
  onmouseleave={() => { hovered = false; confirming = false; }}
>
  <div class="creature-area">
    <div class="orb-container" class:alive class:restarting class:dead={!alive && !restarting}>
      <div class="orb-glow"></div>
      <div class="orb-body">
        <div class="orb-highlight"></div>
      </div>
      <div class="orb-ring"></div>
      <div class="orb-ambient"></div>
    </div>

    <div class="label">
      <span class="name">{displayName}</span>
      <span class="status" class:alive class:restarting>
        {alive ? "alive" : restarting ? "restarting" : "stopped"}
      </span>
    </div>

    <div class="actions" class:visible={hovered}>
      {#if confirming}
        <button class="action-btn danger" onclick={destroy}>confirm</button>
        <button class="action-btn muted" onclick={cancelDestroy}>cancel</button>
      {:else}
        <button class="action-btn" onclick={toggleRun}>
          {alive ? "stop" : "start"}
        </button>
        <button class="action-btn primary" onclick={onConsole}>console</button>
        <button class="action-btn danger" onclick={destroy}>destroy</button>
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
    animation: viewIn 0.6s cubic-bezier(0.16, 1, 0.3, 1);
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
  }

  /* --- Orb --- */
  .orb-container {
    position: relative;
    width: 140px;
    height: 140px;
    transition: filter 0.8s ease;
  }

  .orb-body {
    position: absolute;
    inset: 20px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, #b8ceb0, #7a9e70 50%, #5a7e50);
    box-shadow:
      inset 0 -8px 20px rgba(0, 0, 0, 0.15),
      inset 0 4px 12px rgba(255, 255, 255, 0.15);
    transition: background 0.8s ease, box-shadow 0.8s ease, transform 0.8s ease;
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
    transition: opacity 0.8s ease;
  }

  .orb-glow {
    position: absolute;
    inset: -5px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(138, 180, 120, 0.35), transparent 70%);
    filter: blur(18px);
    transition: opacity 0.8s ease, background 0.8s ease;
  }

  .orb-ring {
    position: absolute;
    inset: 14px;
    border-radius: 50%;
    border: 1px solid rgba(255, 255, 255, 0.08);
    transition: border-color 0.8s ease;
  }

  .orb-ambient {
    position: absolute;
    inset: -30px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(138, 180, 120, 0.08), transparent 70%);
    transition: opacity 0.8s ease, background 0.8s ease;
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
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-6px); }
  }

  @keyframes glow-pulse {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.08); }
  }

  @keyframes orb-breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.03); }
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

  /* Restarting state */
  .orb-container.restarting .orb-body {
    background: radial-gradient(circle at 38% 32%, #f0d48a, #d4a85a 50%, #c0903a);
    animation: restart-pulse 1.5s ease-in-out infinite;
  }

  .orb-container.restarting .orb-glow {
    background: radial-gradient(circle, rgba(212, 168, 90, 0.35), transparent 70%);
    animation: glow-pulse 1.5s ease-in-out infinite;
  }

  .orb-container.restarting .orb-ambient {
    background: radial-gradient(circle, rgba(212, 168, 90, 0.08), transparent 70%);
  }

  @keyframes restart-pulse {
    0%, 100% { transform: scale(0.95); opacity: 0.7; }
    50% { transform: scale(1.02); opacity: 1; }
  }

  /* --- Label --- */
  .label {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }

  .name {
    font-size: 16px;
    font-weight: 550;
    color: #3d3a36;
    letter-spacing: -0.01em;
  }

  .status {
    font-size: 11px;
    font-weight: 450;
    color: #b5aba1;
    letter-spacing: 0.04em;
    text-transform: lowercase;
  }

  .status.alive {
    color: #7a9e70;
  }

  .status.restarting {
    color: #d4a85a;
  }

  /* --- Actions --- */
  .actions {
    display: flex;
    gap: 6px;
    opacity: 0;
    transform: translateY(8px);
    transition: opacity 0.3s cubic-bezier(0.16, 1, 0.3, 1), transform 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    pointer-events: none;
  }

  .actions.visible {
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
  }

  .action-btn {
    padding: 7px 16px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    background: rgba(255, 255, 255, 0.7);
    backdrop-filter: blur(8px);
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    color: #5a5450;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
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
    transform: translateY(0);
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
</style>
