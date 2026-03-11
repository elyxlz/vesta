<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { listAgents } from "../lib/api";
  import type { ListEntry } from "../lib/types";

  let {
    onSelect,
    onCreate,
  }: {
    onSelect: (name: string, wsPort: number) => void;
    onCreate: () => void;
  } = $props();

  let agents = $state<ListEntry[]>([]);
  let poll: ReturnType<typeof setInterval>;

  async function refresh() {
    try {
      const next = await listAgents();
      if (JSON.stringify(next) !== JSON.stringify(agents)) {
        agents = next;
      }
    } catch (e) {
      console.warn("failed to list agents:", e);
    }
  }

  onMount(() => {
    refresh();
    poll = setInterval(refresh, 5000);
  });

  onDestroy(() => {
    clearInterval(poll);
  });

  function statusColor(status: ListEntry["status"]): string {
    if (status === "running") return "green";
    if (status === "dead") return "red";
    return "gray";
  }

</script>

<div class="grid-view">
  <div class="grid">
    {#each agents as agent}
      <button class="card" onclick={() => onSelect(agent.name, agent.ws_port)}>
        <div class="dot {statusColor(agent.status)}"></div>
        <span class="card-name">{agent.name}</span>
        <span class="card-status">{agent.friendly_status}</span>
      </button>
    {/each}
    <button class="card add-card" onclick={onCreate}>
      <div class="add-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
          <path d="M12 5v14M5 12h14"/>
        </svg>
      </div>
      <span class="card-name">new agent</span>
    </button>
  </div>
</div>

<style>
  .grid-view {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    padding: 40px;
    animation: viewIn 0.6s var(--spring);
  }

  @keyframes viewIn {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px;
    max-width: 480px;
    width: 100%;
  }

  .card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 8px;
    padding: 24px 16px;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 12px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    transition: all 0.2s var(--spring-bouncy);
    font-family: inherit;
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

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    transition: all 0.3s ease;
  }

  .dot.green {
    background: #66bb6a;
    box-shadow: 0 0 8px rgba(102, 187, 106, 0.4);
  }

  .dot.gray {
    background: #b0a8a0;
  }

  .dot.red {
    background: #e07070;
    box-shadow: 0 0 8px rgba(224, 112, 112, 0.3);
  }

  .card-name {
    font-size: 14px;
    font-weight: 550;
    color: #3d3a36;
    letter-spacing: -0.01em;
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .card-status {
    font-size: 11px;
    font-weight: 400;
    color: #807870;
    letter-spacing: 0.02em;
  }

  .add-card {
    border-style: dashed;
    border-color: rgba(0, 0, 0, 0.1);
    background: transparent;
  }

  .add-card:hover {
    background: rgba(0, 0, 0, 0.02);
    border-color: rgba(0, 0, 0, 0.15);
  }

  .add-icon {
    color: #b0a8a0;
    transition: color 0.2s ease;
  }

  .add-card:hover .add-icon {
    color: #5a5450;
  }

  @media (prefers-color-scheme: dark) {
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

    .card-status {
      color: #8a8078;
    }

    .add-card {
      border-color: rgba(255, 255, 255, 0.08);
      background: transparent;
    }

    .add-card:hover {
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.12);
    }

    .add-icon {
      color: #6a625a;
    }

    .add-card:hover .add-icon {
      color: #a09890;
    }
  }
</style>
