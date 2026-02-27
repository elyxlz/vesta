<script lang="ts">
  import { onMount, onDestroy, tick } from "svelte";
  import { streamLogs, stopLogs, attachChat, sendMessage, detachChat } from "../lib/api";
  import { stripAnsi } from "../lib/ansi";
  import type { ChatEvent, LogEvent } from "../lib/types";

  let { name, onBack }: { name: string; onBack: () => void } = $props();

  let lines = $state<string[]>([]);
  let input = $state("");
  let attached = $state(false);
  let outputEl: HTMLDivElement;
  let inputEl: HTMLInputElement;

  function scrollToBottom() {
    tick().then(() => {
      if (outputEl) outputEl.scrollTo({ top: outputEl.scrollHeight, behavior: "smooth" });
    });
  }

  function addLine(text: string) {
    const cleaned = stripAnsi(text).trimEnd();
    if (cleaned) {
      lines = [...lines, cleaned];
      scrollToBottom();
    }
  }

  onMount(async () => {
    try {
      await streamLogs((ev: LogEvent) => {
        if (ev.kind === "Line") addLine(ev.text);
        if (ev.kind === "Error") addLine(`error: ${ev.message}`);
      });
    } catch {}

    try {
      await attachChat((ev: ChatEvent) => {
        if (ev.kind === "Attached") {
          attached = true;
          tick().then(() => inputEl?.focus());
        }
        if (ev.kind === "Output") addLine(ev.text);
        if (ev.kind === "Detached") attached = false;
        if (ev.kind === "Error") addLine(`error: ${ev.message}`);
      });
    } catch {}
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

  <div class="output" bind:this={outputEl}>
    {#each lines as line, i (i)}
      <div class="line">{line}</div>
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
      placeholder={attached ? "send a message..." : "connecting..."}
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
    animation: consoleIn 0.35s cubic-bezier(0.16, 1, 0.3, 1);
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
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
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
    color: rgba(255, 255, 255, 0.4);
    letter-spacing: 0.01em;
  }

  .dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: rgba(255, 255, 255, 0.15);
    transition: all 0.4s ease;
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
    scroll-behavior: smooth;
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
    word-break: break-all;
    color: rgba(255, 255, 255, 0.5);
  }

  .empty-state {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
  }

  .empty-dots {
    display: flex;
    gap: 5px;
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
    padding: 14px 20px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.02);
  }

  .prompt-char {
    color: rgba(255, 255, 255, 0.2);
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
    color: rgba(255, 255, 255, 0.12);
  }

  .input-bar input:disabled {
    opacity: 0.3;
  }
</style>
