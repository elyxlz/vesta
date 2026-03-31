<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import { submitAuthCode } from "../lib/api";
  import ProgressBar from "./ProgressBar.svelte";

  let { onCancel }: { onCancel?: () => void } = $props();

  let authUrl = $state<string | null>(null);
  let authCodeNeeded = $state(false);
  let authCodeSubmitted = $state(false);
  let authCode = $state("");
  let error = $state<string | null>(null);
  let unlisteners: (() => void)[] = [];

  async function handleSubmitCode() {
    if (!authCode.trim()) return;
    await submitAuthCode(authCode.trim());
    authCodeNeeded = false;
    authCodeSubmitted = true;
  }

  onMount(() => {
    listen<string>("auth-url", (e) => { authUrl = e.payload; openUrl(e.payload); }).then((fn) => unlisteners.push(fn));
    listen<string>("auth-code-needed", () => { authCodeNeeded = true; }).then((fn) => unlisteners.push(fn));
    listen<string>("auth-code-invalid", () => {
      authCodeNeeded = true;
      authCodeSubmitted = false;
      authCode = "";
      error = "invalid auth code — try again";
    }).then((fn) => unlisteners.push(fn));
  });

  onDestroy(() => { for (const fn of unlisteners) fn(); });
</script>

<div class="auth-flow">
  <h1>authenticate claude</h1>
  {#if authCodeNeeded}
    <p class="sub">paste the code from the browser below.</p>
    <form onsubmit={(e) => { e.preventDefault(); handleSubmitCode(); }}>
      <!-- svelte-ignore a11y_autofocus -->
      <input type="text" class="name-input" placeholder="paste code here" bind:value={authCode} autofocus />
      <button class="btn primary full" type="submit" disabled={!authCode.trim()}>submit</button>
    </form>
  {:else if authCodeSubmitted}
    <p class="sub">verifying code...</p>
    <ProgressBar message="verifying..." />
  {:else if authUrl}
    <p class="sub">authenticate via the browser window that opened.<br/>if it didn't open, use the link below.</p>
    <button class="auth-link" onclick={() => openUrl(authUrl!)}>{authUrl.slice(0, 50)}...</button>
    <ProgressBar message="waiting for authentication..." />
  {:else}
    <p class="sub">opening browser...</p>
    <ProgressBar message="waiting..." />
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}
  {#if onCancel}
    <button class="btn cancel" onclick={onCancel}>cancel</button>
  {/if}
</div>

<style>
  .auth-flow {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
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
    text-align: center;
  }

  .error {
    color: #c45450;
    font-size: 12px;
    margin: 6px 0 8px;
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
    pointer-events: none;
  }

  .btn.full { width: 100%; }

  .btn.cancel {
    background: transparent;
    color: #7a726a;
    margin-top: 16px;
  }

  .btn.cancel:hover { color: #1a1816; }

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
    box-shadow: 0 0 0 3px rgba(139, 126, 116, 0.2);
  }

  .name-input::placeholder { color: #c4bdb5; }

  form {
    display: flex;
    flex-direction: column;
    align-items: center;
    width: 100%;
  }

  .auth-link {
    font-size: 11px;
    color: #7a726a;
    word-break: break-all;
    margin-bottom: 16px;
    text-decoration: underline;
    text-underline-offset: 2px;
    cursor: pointer;
    background: none;
    border: none;
    font-family: inherit;
    transition: color 0.15s;
  }

  .auth-link:hover { color: #1a1816; }

  @media (prefers-color-scheme: dark) {
    h1 { color: #e8e0d8; }
    .sub { color: #8a8078; }
    .name-input {
      background: rgba(255, 255, 255, 0.06);
      border-color: rgba(255, 255, 255, 0.08);
      color: #e8e0d8;
    }
    .name-input:focus { border-color: rgba(255, 255, 255, 0.18); }
    .name-input::placeholder { color: #5a5450; }
    .btn.primary { background: #e8e0d8; color: #1c1b1a; }
    .btn.primary:hover { background: #f0ece7; }
    .btn.cancel { color: #8a8078; }
    .btn.cancel:hover { color: #e8e0d8; }
    .auth-link { color: #8a8078; }
    .auth-link:hover { color: #e8e0d8; }
  }
</style>
