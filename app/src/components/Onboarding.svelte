<script lang="ts">
  import { onDestroy } from "svelte";
  import { open } from "@tauri-apps/plugin-dialog";
  import { createAgent, agentStatus, authenticate, startAgent, waitForReady, restoreAgent, listAgents, connectToServer } from "../lib/api";
  import type { OnboardingStep } from "../lib/types";
  import ProgressBar from "./ProgressBar.svelte";
  import AuthFlow from "./AuthFlow.svelte";

  const { onComplete, onCancel, initialName, serverConfigured }: { onComplete: (name: string) => void; onCancel?: () => void; initialName?: string; serverConfigured?: boolean } = $props();

  // svelte-ignore state_referenced_locally — intentional one-time capture
  let step = $state<OnboardingStep>(initialName || serverConfigured ? "name" : "connect");
  // svelte-ignore state_referenced_locally
  let agentName = $state(initialName ?? "");
  let error = $state<{ friendly: string | null; raw: string } | null>(null);
  let showRawError = $state(false);
  let busy = $state(false);
  let createMsg = $state("");

  let transitioning = $state(false);
  let msgTimer: ReturnType<typeof setInterval> | null = null;
  let cancelled = $state(false);
  let serverUrl = $state("");
  let serverKey = $state("");

  const CREATE_MESSAGES = [
    "setting things up...",
    "preparing email & calendar access...",
    "loading browser & research tools...",
    "setting up reminders & tasks...",
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
    return raw.trim().toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "").replace(/-{2,}/g, "-").replace(/^-|-$/g, "");
  }

  let normalizedPreview = $derived(normalizeName(agentName));

  async function goTo(next: OnboardingStep) {
    transitioning = true;
    await new Promise((r) => setTimeout(r, 150));
    step = next;
    transitioning = false;
  }

  function formatError(msg: string): { friendly: string | null; raw: string } {
    const lower = msg.toLowerCase();
    if (lower.includes("docker") && lower.includes("not installed")) return { friendly: "docker is required but not installed. install docker and try again.", raw: msg };
    if (lower.includes("docker") && (lower.includes("daemon") || lower.includes("not running"))) return { friendly: "docker isn't running. start docker desktop and try again.", raw: msg };
    if (lower.includes("failed to pull")) return { friendly: "couldn't download. check your internet connection and try again.", raw: msg };
    if (lower.includes("failed to run cli")) return { friendly: "something went wrong starting vesta. try reinstalling.", raw: msg };
    if (lower.includes("setup-token") || lower.includes("setup_token")) return { friendly: "authentication setup failed. try closing vesta and reopening it.", raw: msg };
    return { friendly: null, raw: msg };
  }

  function setError(e: unknown, fallback: string) {
    const err = e as { message?: string };
    error = formatError(err.message || fallback);
  }

  function cancelToName() {
    cancelled = true;
    stopMessages();
    busy = false;
    error = null;
    showRawError = false;
    step = "name";
  }

  async function handleCreate() {
    const name = normalizedPreview;
    if (!name || busy) return;
    busy = true;
    error = null;
    cancelled = false;

    startMessages();
    await goTo("creating");

    try {
      const info = await agentStatus(name);
      if (cancelled) return;
      if (info.status !== "not_found") {
        if (info.status === "running" && info.authenticated && info.agent_ready) {
          stopMessages();
          busy = false;
          await goTo("done");
          return;
        }

        if (info.status === "stopped" || info.status === "dead") {
          try {
            await startAgent(name);
          } catch (e) {
            if (cancelled) return;
            stopMessages();
            busy = false;
            setError(e, "failed to start agent");
            await goTo("name");
            return;
          }
        }

        if (cancelled) return;
        stopMessages();
        busy = false;
        await goTo("auth");
        await runAuth();
        return;
      }
    } catch (e) {
      console.warn("agentStatus check failed:", e);
    }

    if (cancelled) return;

    try {
      await createAgent(name);
      if (cancelled) return;
      stopMessages();
      await goTo("auth");
      await runAuth();
    } catch (e) {
      if (cancelled) return;
      stopMessages();
      setError(e, "something went wrong");
      await goTo("name");
    } finally {
      busy = false;
    }
  }

  async function runAuth() {
    const name = normalizedPreview;
    busy = true;
    error = null;
    try {
      await authenticate(name);
      await startAgent(name);
      await waitForReady(name, 30);
      busy = false;
      await goTo("done");
    } catch (e) {
      busy = false;
      setError(e, "authentication failed");
    }
  }

  async function handleRestore() {
    if (busy) return;
    const path = await open({
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
      multiple: false,
      directory: false,
    });
    if (!path) return;
    const before = new Set((await listAgents().catch(() => [])).map((b) => b.name));
    busy = true;
    error = null;
    startMessages();
    await goTo("creating");
    try {
      await restoreAgent(path);
      const after = await listAgents().catch(() => []);
      const restored = after.find((b) => !before.has(b.name));
      if (restored) agentName = restored.name;
      stopMessages();
      busy = false;
      await goTo("done");
    } catch (e) {
      stopMessages();
      busy = false;
      setError(e, "restore failed");
      await goTo("name");
    }
  }

  async function handleConnect() {
    const url = serverUrl.trim();
    const key = serverKey.trim();
    if (!url || !key || busy) return;
    busy = true;
    error = null;
    try {
      await connectToServer(url, key);
      // Connected — check if agents already exist on this server
      const agents = await listAgents().catch(() => []);
      if (agents.length > 0) {
        const agent = agents.find((a) => a.authenticated) ?? agents[0];
        agentName = agent.name;
        busy = false;
        await goTo("done");
      } else {
        busy = false;
        await goTo("name");
      }
    } catch (e) {
      busy = false;
      setError(e, "failed to connect");
    }
  }

  function handleComplete() {
    onComplete(normalizedPreview);
  }

  onDestroy(() => { stopMessages(); });
</script>

<div class="onboarding" class:transitioning>
  {#if onCancel}
    <button class="back-btn" onclick={onCancel} aria-label="back" data-tip="back">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
  {/if}
  <div class="card">
    {#if step === "name"}
      <div class="step step-anim">
        <h1>new agent</h1>
        <p class="sub">give it a name to get started.</p>
        <form onsubmit={(e) => { e.preventDefault(); handleCreate(); }}>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            class="name-input"
            placeholder="name your agent"
            value={agentName}
            oninput={(e) => { agentName = (e.target as HTMLInputElement).value; }}
            autofocus
          />
          {#if error}
            <p class="error">{error.friendly ?? "something went wrong."}</p>
            {#if error.raw.length > 80 || !error.friendly}
              <button type="button" class="btn details-toggle" onclick={() => { showRawError = !showRawError; }}>{showRawError ? "hide details" : "show details"}</button>
              {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
            {/if}
          {/if}
          <button class="btn primary full" type="submit" disabled={!normalizedPreview || busy}>create</button>
        </form>
        <div class="secondary-actions">
          <button class="btn cancel" onclick={handleRestore} disabled={busy}>restore from backup</button>
          {#if !serverConfigured}
            <button class="btn cancel" onclick={() => goTo("connect")} disabled={busy}>connect to server</button>
          {/if}
        </div>
      </div>

    {:else if step === "connect"}
      <div class="step step-anim">
        <h1>connect</h1>
        <p class="sub">connect to a remote vesta server.</p>
        <form onsubmit={(e) => { e.preventDefault(); handleConnect(); }}>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            class="name-input"
            placeholder="host:port"
            value={serverUrl}
            oninput={(e) => { serverUrl = (e.target as HTMLInputElement).value; }}
            autofocus
          />
          <input
            type="password"
            class="name-input"
            placeholder="API key"
            value={serverKey}
            oninput={(e) => { serverKey = (e.target as HTMLInputElement).value; }}
          />
          {#if error}
            <p class="error">{error.friendly ?? "something went wrong."}</p>
            {#if error.raw.length > 80 || !error.friendly}
              <button type="button" class="btn details-toggle" onclick={() => { showRawError = !showRawError; }}>{showRawError ? "hide details" : "show details"}</button>
              {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
            {/if}
          {/if}
          <button class="btn primary full" type="submit" disabled={!serverUrl.trim() || !serverKey.trim() || busy}>connect</button>
        </form>
        <button class="btn cancel" onclick={() => { error = null; goTo("name"); }}>back</button>
      </div>

    {:else if step === "creating"}
      <div class="step step-anim">
        <h1>setting up</h1>
        <p class="sub">this may take a couple of mins.</p>
        <ProgressBar message={createMsg} />
        {#if error}
          <p class="error">{error.friendly ?? "something went wrong."}</p>
          {#if error.raw.length > 80 || !error.friendly}
            <button class="btn details-toggle" onclick={() => { showRawError = !showRawError; }}>{showRawError ? "hide details" : "show details"}</button>
            {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
          {/if}
          <button class="btn primary" onclick={() => goTo("name")}>try again</button>
        {:else}
          <button class="btn cancel" onclick={cancelToName}>cancel</button>
        {/if}
      </div>

    {:else if step === "auth"}
      <div class="step step-anim">
        <AuthFlow onCancel={cancelToName} />
        {#if error}
          <p class="error">{error.friendly ?? "something went wrong."}</p>
          {#if error.raw.length > 80 || !error.friendly}
            <button class="btn details-toggle" onclick={() => { showRawError = !showRawError; }}>{showRawError ? "hide details" : "show details"}</button>
            {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
          {/if}
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
        <h1>{normalizedPreview || "your agent"} is ready</h1>
        <p class="sub">say hi.</p>
        <button class="btn primary" onclick={handleComplete}>continue</button>
      </div>
    {/if}
  </div>
</div>

<style>
  .onboarding {
    position: relative;
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
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
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
    margin: 6px 0 8px;
    font-weight: 450;
    animation: shake 0.3s ease;
    white-space: pre-line;
  }

  .error-details {
    width: 100%;
    max-height: 150px;
    overflow: auto;
    background: rgba(0, 0, 0, 0.04);
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 6px;
    corner-shape: squircle;
    padding: 8px 10px;
    font-size: 10px;
    line-height: 1.4;
    color: #5a524a;
    text-align: left;
    white-space: pre-wrap;
    word-break: break-all;
    margin: 4px 0 10px;
  }

  .btn.details-toggle {
    background: transparent;
    color: #9a928a;
    font-size: 11px;
    padding: 2px 8px;
    min-height: 36px;
    margin-bottom: 4px;
  }

  .btn.details-toggle:hover {
    color: #5a524a;
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
    pointer-events: none;
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
    background: rgba(255, 255, 255, 0.95);
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

  .secondary-actions {
    display: flex;
    flex-direction: column;
    align-items: center;
  }

  .btn.cancel {
    background: transparent;
    color: #7a726a;
    margin-top: 16px;
    font-size: 12px;
    min-height: 36px;
  }

  .btn.cancel:hover {
    color: #1a1816;
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
    .back-btn {
      color: rgba(255, 255, 255, 0.25);
    }
    .back-btn:hover {
      background: rgba(255, 255, 255, 0.06);
      color: rgba(255, 255, 255, 0.6);
    }

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

    .btn.cancel {
      color: #8a8078;
    }

    .btn.cancel:hover {
      color: #e8e0d8;
    }

    .error {
      color: #e07070;
    }

    .error-details {
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.08);
      color: #a09890;
    }

    .btn.details-toggle {
      color: #6a625a;
    }

    .btn.details-toggle:hover {
      color: #a09890;
    }

  }
</style>
