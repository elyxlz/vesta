<script lang="ts">
  import { onDestroy } from "svelte";
  import { createAgent, agentStatus, authenticate, startAgent } from "../lib/api";
  import { agent } from "../lib/stores";
  import ProgressBar from "./ProgressBar.svelte";

  let { onComplete }: { onComplete: (name: string) => void } = $props();

  let step = $state<"name" | "creating" | "auth" | "done">("name");
  let agentName = $state("");
  let error = $state("");
  let transitioning = $state(false);
  let busy = $state(false);
  let createMsg = $state("");
  let msgTimer: ReturnType<typeof setInterval> | null = null;

  const CREATE_MESSAGES = [
    "setting things up...",
    "building your workspace...",
    "preparing skills...",
    "stocking the toolbox...",
    "almost there...",
  ];

  function startMessages() {
    let i = 0;
    createMsg = CREATE_MESSAGES[0];
    msgTimer = setInterval(() => {
      i = (i + 1) % CREATE_MESSAGES.length;
      createMsg = CREATE_MESSAGES[i];
    }, 3000);
  }

  function stopMessages() {
    if (msgTimer) { clearInterval(msgTimer); msgTimer = null; }
  }

  function normalizeName(raw: string): string {
    return raw.trim().toLowerCase().replace(/\s+/g, "-");
  }

  async function goTo(next: typeof step) {
    transitioning = true;
    await new Promise((r) => setTimeout(r, 150));
    step = next;
    error = "";
    transitioning = false;
  }

  async function handleCreate() {
    const name = normalizeName(agentName);
    if (!name || busy) return;
    busy = true;
    error = "";

    try {
      const info = await agentStatus();
      if (info.status !== "not_found") {
        busy = false;
        await goTo("auth");
        runAuth();
        return;
      }
    } catch {}

    startMessages();
    await goTo("creating");
    try {
      await createAgent(name);
      stopMessages();
      await goTo("auth");
      runAuth();
    } catch (e: unknown) {
      stopMessages();
      const err = e as { message?: string };
      error = err.message || "something went wrong";
      await goTo("name");
    } finally {
      busy = false;
    }
  }

  async function runAuth() {
    busy = true;
    error = "";
    try {
      await authenticate();
      await startAgent();
      const info = await agentStatus();
      agent.set(info);
      busy = false;
      await goTo("done");
    } catch (e: unknown) {
      busy = false;
      const err = e as { message?: string };
      error = err.message || "authentication failed";
    }
  }

  onDestroy(() => { stopMessages(); });
</script>

<div class="onboarding" class:transitioning>
  <div class="card">
    {#if step === "name"}
      <div class="step step-anim">
        <h1>welcome to vesta</h1>
        <p class="sub">give it a name to get started.</p>
        <form onsubmit={(e) => { e.preventDefault(); handleCreate(); }}>
          <input
            type="text"
            class="name-input"
            placeholder="e.g. jarvis"
            bind:value={agentName}
          />
          {#if error}<p class="error">{error}</p>{/if}
          <button class="btn primary full" type="submit" disabled={!agentName.trim() || busy}>create</button>
        </form>
      </div>

    {:else if step === "creating"}
      <div class="step step-anim">
        <h1>setting up</h1>
        <p class="sub">this may take a couple of mins.</p>
        <ProgressBar message={createMsg} />
        {#if error}
          <p class="error">{error}</p>
          <button class="btn primary" onclick={() => goTo("name")}>try again</button>
        {/if}
      </div>

    {:else if step === "auth"}
      <div class="step step-anim">
        <h1>sign in to claude</h1>
        <p class="sub">switch to the browser window that opened<br/>and sign in with your anthropic account.</p>
        <ProgressBar message="waiting for sign in..." />
        {#if error}
          <p class="error">{error}</p>
          <button class="btn primary" onclick={runAuth}>retry</button>
        {/if}
      </div>

    {:else if step === "done"}
      <div class="step step-anim">
        <div class="done-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
        </div>
        <h1>you're all set</h1>
        <p class="sub">say hi.</p>
        <button class="btn primary" onclick={() => onComplete(normalizeName(agentName))}>continue</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .onboarding {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    height: 100%;
    padding: 40px;
    transition: opacity 0.25s ease;
  }

  .onboarding.transitioning {
    opacity: 0.7;
  }

  .step-anim {
    animation: fadeSlideIn 0.5s var(--spring);
  }

  @keyframes fadeSlideIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .card {
    max-width: 360px;
    width: 100%;
    text-align: center;
  }

  .step {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  h1 {
    font-size: 22px;
    font-weight: 600;
    color: #1a1816;
    margin-bottom: 8px;
    letter-spacing: -0.03em;
  }

  .sub {
    font-size: 13px;
    color: #7a726a;
    margin-bottom: 28px;
    line-height: 1.6;
    font-weight: 400;
  }

  .error {
    color: #c45450;
    font-size: 12px;
    margin: 6px 0 12px;
    font-weight: 450;
    animation: shake 0.3s ease;
  }

  @keyframes shake {
    0%, 100% { transform: translateX(0); }
    25% { transform: translateX(-3px); }
    75% { transform: translateX(3px); }
  }

  .btn {
    padding: 8px 24px;
    border-radius: 8px;
    corner-shape: squircle;
    font-size: 13px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    border: none;
    transition: all 0.2s var(--spring-bouncy);
    letter-spacing: 0.01em;
  }

  .btn.primary {
    background: #1a1816;
    color: #f0ece7;
  }

  .btn.primary:hover {
    background: #2d2a26;
    transform: translateY(-1px);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  }

  .btn.primary:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .btn.primary:disabled {
    opacity: 0.25;
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
  }

  .btn.full {
    width: 100%;
  }

  .name-input {
    width: 100%;
    padding: 12px 16px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    corner-shape: squircle;
    font-size: 14px;
    font-family: inherit;
    background: white;
    color: #1a1816;
    margin-bottom: 12px;
    outline: none;
    transition: all 0.2s var(--spring);
    text-align: center;
    letter-spacing: 0.01em;
  }

  .name-input:focus {
    border-color: rgba(0, 0, 0, 0.2);
    box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.03);
    outline: none;
  }

  .name-input:focus-visible {
    border-color: rgba(0, 0, 0, 0.2);
    box-shadow: 0 0 0 3px rgba(139, 126, 116, 0.2);
    outline: none;
  }

  .name-input::placeholder {
    color: #c4bdb5;
  }

  form {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
  }

  .done-icon {
    color: #66bb6a;
    margin-bottom: 14px;
    animation: popIn 0.4s var(--spring-bouncy);
  }

  @keyframes popIn {
    from { opacity: 0; transform: scale(0.5); }
    to { opacity: 1; transform: scale(1); }
  }

  @media (prefers-color-scheme: dark) {
    h1 {
      color: #e8e0d8;
    }

    .sub {
      color: #8a8078;
    }

    .name-input {
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.08);
      color: #e8e0d8;
    }

    .name-input::placeholder {
      color: #5a5450;
    }

    .name-input:focus {
      border-color: rgba(255, 255, 255, 0.15);
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.04);
    }

    .name-input:focus-visible {
      box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.1);
    }

    .btn.primary {
      background: #e8e0d8;
      color: #1c1b1a;
    }

    .btn.primary:hover {
      background: #f0ece7;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
    }

    .error {
      color: #e07070;
    }
  }
</style>
