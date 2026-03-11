<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { createAgent, agentStatus, authenticate, startAgent, waitForReady, checkPlatform, setupPlatform } from "../lib/api";
  import type { PlatformStatus } from "../lib/types";
  import ProgressBar from "./ProgressBar.svelte";

  let { onComplete }: { onComplete: (name: string) => void } = $props();

  let step = $state<"platform" | "name" | "creating" | "auth" | "done">("platform");
  let agentName = $state("");
  let error = $state<{ friendly: string | null; raw: string } | null>(null);
  let transitioning = $state(false);
  let busy = $state(false);
  let createMsg = $state("");
  let msgTimer: ReturnType<typeof setInterval> | null = null;
  let cancelled = $state(false);
  let platform = $state<PlatformStatus | null>(null);

  const CREATE_MESSAGES = [
    "setting things up...",
    "preparing email & calendar access...",
    "loading browser & research tools...",
    "setting up reminders & tasks...",
    "almost there...",
  ];

  onMount(async () => {
    try {
      const status = await checkPlatform();
      platform = status;
      if (status.ready || status.platform !== "windows") {
        await goTo("name");
        return;
      }
      // auto-run setup for distro/service issues (WSL already installed)
      if (status.wsl_installed && !status.needs_reboot && status.virtualization_enabled !== false) {
        await handlePlatformSetup();
      }
    } catch (e) {
      setError(e, "failed to check platform");
    }
  });

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

  async function goTo(next: typeof step) {
    transitioning = true;
    await new Promise((r) => setTimeout(r, 150));
    step = next;
    transitioning = false;
  }

  function formatError(msg: string): { friendly: string | null; raw: string } {
    const lower = msg.toLowerCase();
    if (lower.includes("reboot")) return { friendly: "restart your computer to finish setup, then reopen vesta.", raw: msg };
    if (lower.includes("wsl") && lower.includes("not installed")) return { friendly: "WSL2 is required but not installed. open PowerShell as admin and run:\n\nwsl --install --no-distribution\n\nthen restart your computer and reopen vesta.", raw: msg };
    if (lower.includes("wsl") && (lower.includes("virtualization") || lower.includes("bios"))) return { friendly: "WSL2 needs hardware virtualization enabled. restart your computer, enter BIOS/UEFI settings, enable virtualization (Intel VT-x or AMD-V), then try again.", raw: msg };
    if (lower.includes("wsl") && lower.includes("failed")) return { friendly: "WSL2 setup failed. open PowerShell as admin and run:\n\nwsl --install --no-distribution\n\nthen restart your computer and reopen vesta.", raw: msg };
    if (lower.includes("rootfs") && lower.includes("download")) return { friendly: "couldn't download vesta. check your internet connection and try again.", raw: msg };
    if (lower.includes("services did not start")) return { friendly: "services didn't start in time. try closing vesta and reopening it.", raw: msg };
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

  let showRawError = $state(false);

  function cancelToName() {
    cancelled = true;
    stopMessages();
    busy = false;
    error = null;
    showRawError = false;
    step = "name";
  }

  async function recheckPlatform() {
    busy = true;
    error = null;
    try {
      const status = await checkPlatform();
      platform = status;
      if (status.ready) {
        await goTo("name");
      }
    } catch (e) {
      setError(e, "failed to check platform");
    } finally {
      busy = false;
    }
  }

  async function handlePlatformSetup() {
    busy = true;
    error = null;
    try {
      const result = await setupPlatform();
      platform = result;
      if (result.ready) {
        await goTo("name");
      } else if (result.needs_reboot) {
        // stay on platform step, UI will show reboot message
      } else if (result.message) {
        error = { friendly: result.message, raw: result.message };
      }
    } catch (e) {
      setError(e, "setup failed");
    } finally {
      busy = false;
    }
  }

  async function waitUntilReady(agentName: string) {
    await waitForReady(agentName, 30);
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
      await waitUntilReady(name);
      busy = false;
      await goTo("done");
    } catch (e) {
      busy = false;
      setError(e, "authentication failed");
    }
  }

  onDestroy(() => { stopMessages(); });
</script>

<div class="onboarding" class:transitioning>
  <div class="card">
    {#if step === "platform"}
      <div class="step step-anim">
        {#if !platform}
          <h1>checking system</h1>
          <p class="sub">making sure everything is ready...</p>
          <ProgressBar message="checking..." />
        {:else if platform.needs_reboot}
          <div class="platform-icon">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
              <path d="M21 3v5h-5"/>
            </svg>
          </div>
          <h1>restart required</h1>
          <p class="sub">WSL2 was installed successfully.<br/>restart your computer to finish setup, then reopen vesta.</p>
          <button class="btn primary" onclick={recheckPlatform} disabled={busy}>check again</button>
        {:else if platform.virtualization_enabled === false}
          <div class="platform-icon warn">
            <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>
              <line x1="12" y1="9" x2="12" y2="13"/>
              <line x1="12" y1="17" x2="12.01" y2="17"/>
            </svg>
          </div>
          <h1>enable virtualization</h1>
          <p class="sub">
            WSL2 needs hardware virtualization enabled.<br/><br/>
            1. restart your computer<br/>
            2. press the BIOS key during boot<br/>
            <span class="hint">(usually F2, F10, F12, or Del)</span><br/>
            3. find and enable <strong>Intel VT-x</strong> or <strong>AMD-V</strong><br/>
            4. save and exit BIOS, then reopen vesta
          </p>
          <button class="btn primary" onclick={recheckPlatform} disabled={busy}>check again</button>
        {:else if !platform.wsl_installed}
          <h1>setting up windows</h1>
          <p class="sub">vesta needs WSL2 to run.<br/>click below to install it automatically.</p>
          {#if error}
            <p class="error">{error.friendly ?? "something went wrong."}</p>
            {#if error.raw.length > 80 || !error.friendly}
              <button class="btn details-toggle" onclick={() => showRawError = !showRawError}>{showRawError ? "hide details" : "show details"}</button>
              {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
            {/if}
          {/if}
          {#if busy}
            <ProgressBar message="installing WSL2... you may see a permission prompt." />
          {:else}
            <button class="btn primary full" onclick={handlePlatformSetup}>install WSL2</button>
          {/if}
        {:else}
          <h1>setting up</h1>
          <p class="sub">preparing vesta's environment...</p>
          {#if error}
            <p class="error">{error.friendly ?? "something went wrong."}</p>
            <button class="btn primary" onclick={handlePlatformSetup} disabled={busy}>retry</button>
          {:else}
            <ProgressBar message="setting up..." />
          {/if}
        {/if}
      </div>

    {:else if step === "name"}
      <div class="step step-anim">
        <h1>welcome to vesta</h1>
        <p class="sub">give it a name to get started.</p>
        <form onsubmit={(e) => { e.preventDefault(); handleCreate(); }}>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            class="name-input"
            placeholder="e.g. jarvis"
            bind:value={agentName}
            autofocus
          />
          {#if agentName.trim() && normalizedPreview !== agentName.trim()}<p class="name-preview">{normalizedPreview}</p>{/if}
          {#if error}
            <p class="error">{error.friendly ?? "something went wrong."}</p>
            {#if error.raw.length > 80 || !error.friendly}
              <button type="button" class="btn details-toggle" onclick={() => showRawError = !showRawError}>{showRawError ? "hide details" : "show details"}</button>
              {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
            {/if}
          {/if}
          <button class="btn primary full" type="submit" disabled={!normalizedPreview || busy}>create</button>
        </form>
      </div>

    {:else if step === "creating"}
      <div class="step step-anim">
        <h1>setting up</h1>
        <p class="sub">this may take a couple of mins.</p>
        <ProgressBar message={createMsg} />
        {#if error}
          <p class="error">{error.friendly ?? "something went wrong."}</p>
          {#if error.raw.length > 80 || !error.friendly}
            <button class="btn details-toggle" onclick={() => showRawError = !showRawError}>{showRawError ? "hide details" : "show details"}</button>
            {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
          {/if}
          <button class="btn primary" onclick={() => goTo("name")}>try again</button>
        {:else}
          <button class="btn cancel" onclick={cancelToName}>cancel</button>
        {/if}
      </div>

    {:else if step === "auth"}
      <div class="step step-anim">
        <h1>sign in to claude</h1>
        <p class="sub">switch to the browser window that opened<br/>and sign in with your anthropic account.</p>
        <ProgressBar message="waiting for sign in..." />
        {#if error}
          <p class="error">{error.friendly ?? "something went wrong."}</p>
          {#if error.raw.length > 80 || !error.friendly}
            <button class="btn details-toggle" onclick={() => showRawError = !showRawError}>{showRawError ? "hide details" : "show details"}</button>
            {#if showRawError}<pre class="error-details">{error.raw}</pre>{/if}
          {/if}
          <button class="btn primary" onclick={runAuth}>retry</button>
        {/if}
        <button class="btn cancel" onclick={cancelToName}>cancel</button>
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

  .sub .hint {
    font-size: 11px;
    color: #9a928a;
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

  .name-preview {
    font-size: 11px;
    color: #7a726a;
    margin: -6px 0 8px;
    font-weight: 400;
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

  .platform-icon {
    color: #7a726a;
    margin-bottom: 14px;
    animation: popIn 0.4s var(--spring-bouncy);
  }

  .platform-icon.warn {
    color: #e0a030;
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

    .sub .hint {
      color: #6a625a;
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

    .name-preview {
      color: #8a8078;
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

    .platform-icon {
      color: #8a8078;
    }

    .platform-icon.warn {
      color: #e0a030;
    }
  }
</style>
