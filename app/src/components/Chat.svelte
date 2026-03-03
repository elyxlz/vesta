<script lang="ts">
  import { onDestroy } from "svelte";
  import { messages, connected, agentState } from "../lib/stores";
  import { send } from "../lib/ws";
  import { linkify } from "../lib/linkify";
  import { createAutoScroller } from "../lib/scroll";
  import "../styles/panel.css";
  import type { VestaEvent } from "../lib/types";

  let { name, onBack }: { name: string; onBack: () => void } = $props();

  type Line = { id: number; text: string; kind: string };
  let lines = $state<Line[]>([]);
  let nextId = 0;
  let input = $state("");
  let showTools = $state(false);
  let outputEl: HTMLDivElement;
  let inputEl: HTMLTextAreaElement;

  let wasConnected = $state(false);
  const scroller = createAutoScroller(() => outputEl);

  function eventToLine(ev: VestaEvent): Line | null {
    if (ev.type === "user") return { id: nextId++, text: `> ${ev.text}`, kind: "user" };
    if (ev.type === "assistant") return { id: nextId++, text: ev.text, kind: "assistant" };
    if (ev.type === "tool_start") return { id: nextId++, text: `[${ev.tool}] ${ev.input}`, kind: "tool" };
    if (ev.type === "tool_end") return { id: nextId++, text: `[${ev.tool}] done`, kind: "tool" };
    if (ev.type === "notification") return { id: nextId++, text: `[${ev.source}] ${ev.summary}`, kind: "notification" };
    if (ev.type === "error") return { id: nextId++, text: `error: ${ev.text}`, kind: "error" };
    return null;
  }

  let lastSyncedLen = 0;
  let lastArray: VestaEvent[] = [];

  let pendingUserTexts = new Map<string, number>();

  const unsubMessages = messages.subscribe((evts) => {
    if (evts !== lastArray) {
      lines = [];
      nextId = 0;
      lastSyncedLen = 0;
      pendingUserTexts.clear();
    }
    for (let i = lastSyncedLen; i < evts.length; i++) {
      const ev = evts[i];
      if (ev.type === "user") {
        const count = pendingUserTexts.get(ev.text) ?? 0;
        if (count > 0) {
          if (count === 1) pendingUserTexts.delete(ev.text);
          else pendingUserTexts.set(ev.text, count - 1);
          continue;
        }
      }
      const line = eventToLine(ev);
      if (line) lines.push(line);
    }
    lastSyncedLen = evts.length;
    lastArray = evts;
    lines = lines;
    scroller.scroll();
  });

  $effect(() => {
    if ($connected) {
      wasConnected = true;
      tick().then(() => inputEl?.focus());
    }
  });

  onDestroy(() => {
    unsubMessages();
  });

  function handleSend() {
    const msg = input.trim();
    if (!msg) return;
    if (send(msg)) {
      pendingUserTexts.set(msg, (pendingUserTexts.get(msg) ?? 0) + 1);
      lines.push({ id: nextId++, text: `> ${msg}`, kind: "user" });
      lines = lines;
      scroller.scroll();
      input = "";
      resizeInput();
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function resizeInput() {
    if (!inputEl) return;
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  }

  let thinking = $derived($agentState === "thinking" || $agentState === "tool_use");
</script>

<div class="panel">
  <div class="topbar">
    <button class="back-btn" onclick={onBack} aria-label="back" data-tip="back">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
    <div class="topbar-info">
      <span class="title">{name}</span>
      <span class="dot" class:connected={$connected}></span>
    </div>
    <button class="tool-toggle" class:active={showTools} onclick={() => (showTools = !showTools)} aria-label="show tool activity" data-tip={showTools ? "hide tools" : "show tools"}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
      </svg>
    </button>
  </div>

  <div class="output" bind:this={outputEl} onscroll={scroller.check}>
    {#each lines as line (line.id)}
      {#if (line.kind !== "tool" && line.kind !== "notification") || showTools}
        <div class="line {line.kind}">{@html linkify(line.text)}</div>
      {/if}
    {/each}
    {#if thinking && lines.length > 0}
      <div class="line thinking-indicator"><span></span><span></span><span></span></div>
    {/if}
    {#if lines.length === 0}
      <div class="empty-state">
        <div class="empty-dots"><span></span><span></span><span></span></div>
        <span class="empty-label">{$connected ? "" : "connecting..."}</span>
      </div>
    {/if}
  </div>

  {#if !$connected && wasConnected}
    <div class="reconnect-bar">reconnecting...</div>
  {/if}

  <form class="input-bar" onsubmit={(e) => { e.preventDefault(); handleSend(); }}>
    <span class="prompt-char">&gt;</span>
    <textarea
      rows="1"
      placeholder={$connected ? "send a message..." : "connecting..."}
      bind:value={input}
      bind:this={inputEl}
      disabled={!$connected}
      oninput={resizeInput}
      onkeydown={handleKeydown}
    ></textarea>
  </form>
</div>

<style>
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

  .tool-toggle {
    margin-left: auto;
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.25);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: 4px;
    transition: all 0.2s var(--spring);
    display: flex;
    align-items: center;
  }

  .tool-toggle:hover {
    color: rgba(255, 255, 255, 0.5);
    background: rgba(255, 255, 255, 0.05);
  }

  .tool-toggle.active {
    color: rgba(255, 255, 255, 0.7);
    background: rgba(255, 255, 255, 0.08);
  }

  .line.user { color: rgba(255, 255, 255, 0.9); }
  .line.assistant { color: rgba(140, 200, 130, 0.9); }
  .line.tool { color: rgba(255, 255, 255, 0.4); font-size: 11px; }
  .line.notification { color: rgba(255, 200, 100, 0.7); font-size: 11px; }
  .line.error { color: rgba(224, 112, 112, 0.9); }

  .thinking-indicator {
    display: flex;
    gap: 4px;
    padding: 4px 0;
  }

  .thinking-indicator span {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: rgba(140, 200, 130, 0.5);
    animation: dot-pulse 1.4s ease-in-out infinite;
  }

  .thinking-indicator span:nth-child(2) { animation-delay: 0.2s; }
  .thinking-indicator span:nth-child(3) { animation-delay: 0.4s; }

  .reconnect-bar {
    padding: 6px 20px;
    font-size: 11px;
    color: rgba(255, 200, 100, 0.8);
    background: rgba(255, 200, 100, 0.06);
    border-top: 1px solid rgba(255, 200, 100, 0.1);
    text-align: center;
    animation: lineIn 0.15s ease-out;
  }

  .input-bar {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 12px 20px;
    border-top: 1px solid rgba(255, 255, 255, 0.05);
    flex-shrink: 0;
    background: rgba(255, 255, 255, 0.02);
  }

  .prompt-char {
    color: rgba(255, 255, 255, 0.35);
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.4;
    font-weight: 500;
    flex-shrink: 0;
    user-select: none;
  }

  .input-bar textarea {
    flex: 1;
    background: transparent;
    border: none;
    outline: none;
    resize: none;
    overflow-y: auto;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.4;
    color: rgba(255, 255, 255, 0.75);
    caret-color: rgba(255, 255, 255, 0.4);
    max-height: 120px;
  }

  .input-bar textarea::placeholder { color: rgba(255, 255, 255, 0.35); }
  .input-bar textarea:disabled { opacity: 0.25; }
</style>
