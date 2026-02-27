<script lang="ts">
  import { open } from "@tauri-apps/plugin-shell";
  import { createAgent, startAgent, startAuth, agentStatus } from "../lib/api";
  import { agent } from "../lib/stores";
  import ProgressBar from "./ProgressBar.svelte";
  import type { AuthEvent } from "../lib/types";

  let { onComplete }: { onComplete: (name: string) => void } = $props();

  let step = $state<"name" | "creating" | "auth" | "done">("name");
  let agentName = $state("");
  let authOutput = $state("");
  let error = $state("");
  let transitioning = $state(false);
  let createMsg = $state("");

  async function goTo(next: typeof step) {
    transitioning = true;
    await new Promise((r) => setTimeout(r, 200));
    step = next;
    error = "";
    transitioning = false;
  }

  async function handleCreate() {
    const name = agentName.trim().toLowerCase().replace(/\s+/g, "-");
    if (!name) return;
    error = "";
    createMsg = "creating agent...";
    goTo("creating");
    try {
      await createAgent();
      createMsg = "starting...";
      await startAgent();
      const info = await agentStatus();
      agent.set(info);
      goTo("auth");
      runAuth();
    } catch (e: any) {
      error = e?.message ?? "couldn't create agent";
      goTo("name");
    }
  }

  function runAuth() {
    authOutput = "";
    startAuth((ev: AuthEvent) => {
      if (ev.kind === "Output") authOutput += ev.text;
      if (ev.kind === "UrlDetected") open(ev.url);
      if (ev.kind === "Complete") goTo("done");
      if (ev.kind === "Error") error = ev.message;
    });
  }
</script>

<div class="onboarding" class:transitioning>
  <div class="card">
    {#if step === "name"}
      <div class="step" style="animation: fadeSlideIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)">
        <h1>welcome to vesta</h1>
        <p class="sub">your personal ai assistant.<br/>give it a name to get started.</p>
        <form onsubmit={(e) => { e.preventDefault(); handleCreate(); }}>
          <input
            type="text"
            class="name-input"
            placeholder="e.g. jarvis"
            bind:value={agentName}
          />
          {#if error}<p class="error">{error}</p>{/if}
          <button class="btn primary full" type="submit" disabled={!agentName.trim()}>create</button>
        </form>
      </div>

    {:else if step === "creating"}
      <div class="step" style="animation: fadeSlideIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)">
        <h1>setting up</h1>
        <p class="sub">pulling image and starting your agent.<br/>this takes a moment the first time.</p>
        <ProgressBar message={createMsg} />
        {#if error}
          <p class="error">{error}</p>
          <button class="btn primary" onclick={() => goTo("welcome")}>try again</button>
        {/if}
      </div>

    {:else if step === "auth"}
      <div class="step" style="animation: fadeSlideIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)">
        <h1>sign in to claude</h1>
        <p class="sub">a browser window should open.<br/>sign in, then come back.</p>
        {#if authOutput}
          <div class="auth-box">{authOutput}</div>
        {/if}
        {#if error}<p class="error">{error}</p>{/if}
        <ProgressBar message="waiting for sign in..." />
      </div>

    {:else if step === "done"}
      <div class="step" style="animation: fadeSlideIn 0.5s cubic-bezier(0.16, 1, 0.3, 1)">
        <div class="done-icon">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
        </div>
        <h1>you're all set</h1>
        <p class="sub">your agent is ready.</p>
        <button class="btn primary" onclick={() => onComplete(agentName.trim().toLowerCase().replace(/\s+/g, "-"))}>continue</button>
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
    opacity: 0.3;
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
    color: #a09890;
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
    padding: 9px 22px;
    border-radius: 9px;
    font-size: 13px;
    font-weight: 500;
    font-family: inherit;
    cursor: pointer;
    border: none;
    transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
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
    transform: translateY(0);
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
    border-radius: 9px;
    font-size: 14px;
    font-family: inherit;
    background: white;
    color: #1a1816;
    margin-bottom: 12px;
    outline: none;
    transition: all 0.2s ease;
    text-align: center;
    letter-spacing: 0.01em;
  }

  .name-input:focus {
    border-color: rgba(0, 0, 0, 0.2);
    box-shadow: 0 0 0 3px rgba(0, 0, 0, 0.03);
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

  .auth-box {
    background: rgba(0, 0, 0, 0.03);
    border-radius: 9px;
    padding: 12px 14px;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 11px;
    text-align: left;
    max-height: 140px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
    color: #8b7e74;
    margin-bottom: 18px;
    width: 100%;
    line-height: 1.5;
    border: 1px solid rgba(0, 0, 0, 0.04);
  }

  .done-icon {
    color: #66bb6a;
    margin-bottom: 14px;
    animation: popIn 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
  }

  @keyframes popIn {
    from { opacity: 0; transform: scale(0.5); }
    to { opacity: 1; transform: scale(1); }
  }
</style>
