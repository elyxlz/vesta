<script lang="ts">
  import { onMount, onDestroy, tick } from "svelte";
  import { streamLogs, stopLogs, attachChat, sendMessage, detachChat } from "../lib/api";
  import { stripAnsi } from "../lib/ansi";
  import type { ChatEvent, LogEvent } from "../lib/types";

  let { name, onBack }: { name: string; onBack: () => void } = $props();

  type Line = { id: number; text: string };
  let lines = $state<Line[]>([]);
  let nextId = 0;
  let input = $state("");
  let attached = $state(false);
  let connectFailed = $state(false);
  let outputEl: HTMLDivElement;
  let inputEl: HTMLInputElement;

  let wasNearBottom = true;

  function checkNearBottom() {
    if (!outputEl) return;
    wasNearBottom = outputEl.scrollHeight - outputEl.scrollTop - outputEl.clientHeight < 40;
  }

  function scrollToBottom() {
    tick().then(() => {
      if (outputEl && wasNearBottom) {
        outputEl.scrollTop = outputEl.scrollHeight;
      }
    });
  }

  const MAX_LINES = 500;

  function addLine(text: string) {
    const cleaned = stripAnsi(text).trimEnd();
    if (cleaned) {
      const entry: Line = { id: nextId++, text: cleaned };
      const updated = [...lines, entry];
      lines = updated.length > MAX_LINES ? updated.slice(-MAX_LINES) : updated;
      scrollToBottom();
    }
  }

  onMount(async () => {
    try {
      await streamLogs((ev: LogEvent) => {
        if (ev.kind === "Line") addLine(ev.text);
        if (ev.kind === "Error") addLine(`error: ${ev.message}`);
      });
    } catch (e) { console.error("streamLogs failed:", e); }

    try {
      await attachChat((ev: ChatEvent) => {
        if (ev.kind === "Attached") {
          attached = true;
          connectFailed = false;
          tick().then(() => inputEl?.focus());
        }
        if (ev.kind === "Output") addLine(ev.text);
        if (ev.kind === "Detached") { attached = false; connectFailed = true; }
      });
    } catch (e) {
      console.error("attachChat failed:", e);
      connectFailed = true;
    }
  });

  onDestroy(async () => {
    try { await stopLogs(); } catch {}
    try { await detachChat(); } catch {}
  });

  async function handleSend() {
    const msg = input.trim();
    if (!msg) return;
    input = "";
    addLine(`> ${msg}`);
    try {
      await sendMessage(msg);
    } catch (e) {
      addLine(`send failed: ${e}`);
    }
  }
</script>

<div class="console">
  <div class="topbar">
    <button class="back-btn" onclick={onBack} aria-label="back to agent">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
    <div class="topbar-info">
      <span class="title">{name}</span>
      <span class="dot" class:connected={attached}></span>
    </div>
  </div>

  <div class="output" bind:this={outputEl} onscroll={checkNearBottom}>
    {#each lines as line (line.id)}
      <div class="line">{line.text}</div>
    {/each}
    {#if lines.length === 0}
      <div class="empty-state">
        <div class="empty-dots"><span></span><span></span><span></span></div>
      </div>
    {/if}
  </div>

  <form class="input-bar" onsubmit={(e) => { e.preventDefault(); handleSend(); }}>
    <span class="prompt-char">&gt;</span>
    <input
      type="text"
      placeholder={attached ? "send a message..." : connectFailed ? "disconnected" : "connecting..."}
      bind:value={input}
      bind:this={inputEl}
      disabled={!attached}
    />
  </form>
</div>

<style>
  .console {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    animation: consoleIn 0.35s var(--spring);
  }

  @keyframes consoleIn {
    from { opacity: 0; }
    to { opacity: 1; }
  }

  .topbar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    flex-shrink: 0;
  }

  .back-btn {
    width: 30px;
    height: 30px;
    border: none;
    background: transparent;
    color: rgba(255, 255, 255, 0.25);
    cursor: pointer;
    border-radius: 8px;
    corner-shape: squircle;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
  }

  .back-btn:hover {
    background: rgba(255, 255, 255, 0.06);
    color: rgba(255, 255, 255, 0.6);
  }

  .topbar-info {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .title {
    font-size: 13px;
    font-weight: 500;
    color: rgba(255, 255, 255, 0.55);
    letter-spacing: 0.01em;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.15);
    transition: all 0.4s var(--spring);
  }

  .dot.connected {
    background: #66bb6a;
    box-shadow: 0 0 6px rgba(102, 187, 106, 0.4);
  }

  .output {
    flex: 1;
    overflow-y: auto;
    padding: 16px 20px;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 12px;
    line-height: 1.75;
    min-height: 0;
  }

  .output::-webkit-scrollbar {
    width: 6px;
  }

  .output::-webkit-scrollbar-track {
    background: transparent;
  }

  .output::-webkit-scrollbar-thumb {
    background: rgba(255, 255, 255, 0.08);
    border-radius: 3px;
  }

  .output::-webkit-scrollbar-thumb:hover {
    background: rgba(255, 255, 255, 0.14);
  }

  .line {
    white-space: pre-wrap;
    overflow-wrap: break-word;
    color: rgba(255, 255, 255, 0.7);
    animation: lineIn 0.15s ease-out;
  }

  @keyframes lineIn {
    from { opacity: 0; transform: translateY(2px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
  }

  .empty-dots {
    display: flex;
    gap: 4px;
  }

  .empty-dots span {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.12);
    animation: dot-pulse 1.4s ease-in-out infinite;
  }

  .empty-dots span:nth-child(2) { animation-delay: 0.2s; }
  .empty-dots span:nth-child(3) { animation-delay: 0.4s; }

  @keyframes dot-pulse {
    0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
    40% { opacity: 1; transform: scale(1); }
  }

  .input-bar {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 20px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.02);
  }

  .prompt-char {
    color: rgba(255, 255, 255, 0.35);
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    font-weight: 500;
    flex-shrink: 0;
    user-select: none;
  }

  .input-bar input {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    color: rgba(255, 255, 255, 0.75);
    caret-color: rgba(255, 255, 255, 0.4);
  }

  .input-bar input::placeholder {
    color: rgba(255, 255, 255, 0.35);
  }

  .input-bar input:disabled {
    opacity: 0.3;
  }
</style>
