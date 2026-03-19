<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import { get } from "svelte/store";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import type { BoxConnection } from "../lib/ws";
  import { linkify } from "../lib/linkify";
  import { createAutoScroller } from "../lib/scroll";
  import "../styles/panel.css";
  import type { VestaEvent, BoxActivityState } from "../lib/types";

  let { name, connection, onBack }: { name: string; connection: BoxConnection; onBack: () => void } = $props();

  type Line = { id: number; text: string; kind: string; time: string };
  const MAX_MESSAGES = 5000;
  let lines = $state<Line[]>([]);
  let nextId = 0;
  let input = $state("");
  let showTools = $state(false);
  let outputEl: HTMLDivElement;
  let inputEl: HTMLTextAreaElement;

  let wasConnected = $state(false);
  let suppressAnim = $state(false);
  const scroller = createAutoScroller(() => outputEl);

  let connectedVal = $state(get(connection.connected));
  let boxStateVal = $state<BoxActivityState>(get(connection.boxState));

  $effect(() => {
    const u1 = connection.connected.subscribe((v: boolean) => { connectedVal = v; });
    const u2 = connection.boxState.subscribe((v: BoxActivityState) => { boxStateVal = v; });
    return () => { u1(); u2(); };
  });

  function fmtTime(iso?: string) {
    if (!iso) return "";
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  function eventToLine(ev: VestaEvent): Line | null {
    const time = fmtTime(ev.ts);
    if (ev.type === "user") return { id: nextId++, text: `> ${ev.text}`, kind: "user", time };
    if (ev.type === "assistant") return { id: nextId++, text: ev.text, kind: "assistant", time };
    if (ev.type === "tool_start") return { id: nextId++, text: `[${ev.tool}] ${ev.input}`, kind: "tool", time };
    if (ev.type === "tool_end") return { id: nextId++, text: `[${ev.tool}] done`, kind: "tool", time };
    if (ev.type === "notification") return { id: nextId++, text: `[${ev.source}] ${ev.summary}`, kind: "notification", time };
    if (ev.type === "error") return { id: nextId++, text: `error: ${ev.text}`, kind: "error", time };
    return null;
  }

  let lastSyncedLen = 0;

  let pendingUserTexts = new Map<string, number>();

  $effect(() => {
    const unsub = connection.messages.subscribe((evts: VestaEvent[]) => {
      if (evts.length < lastSyncedLen) {
        lines = [];
        nextId = 0;
        lastSyncedLen = 0;
        pendingUserTexts.clear();
        suppressAnim = true;
        requestAnimationFrame(() => { suppressAnim = false; });
      }
      if (evts.length === lastSyncedLen) return;
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
      if (lines.length > MAX_MESSAGES) lines.splice(0, lines.length - MAX_MESSAGES);
      lastSyncedLen = evts.length;
      lines = lines;
      scroller.scroll();
    });
    return () => unsub();
  });

  $effect(() => {
    if (connectedVal) {
      wasConnected = true;
      tick().then(() => inputEl?.focus());
    }
  });

  function handleSend() {
    const msg = input.trim();
    if (!msg) return;
    if (connection.send(msg)) {
      pendingUserTexts.set(msg, (pendingUserTexts.get(msg) ?? 0) + 1);
      lines.push({ id: nextId++, text: `> ${msg}`, kind: "user", time: fmtTime(new Date().toISOString()) });
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

  function handleGlobalKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && (!input.trim() || document.activeElement !== inputEl)) {
      onBack();
    }
  }

  function resizeInput() {
    if (!inputEl) return;
    inputEl.style.height = "auto";
    inputEl.style.height = Math.min(inputEl.scrollHeight, 120) + "px";
  }

  let thinking = $derived(boxStateVal === "thinking" || boxStateVal === "tool_use");

  let stableConnected = $state(false);
  let disconnectTimer: ReturnType<typeof setTimeout> | null = null;
  $effect(() => {
    if (connectedVal) {
      if (disconnectTimer) { clearTimeout(disconnectTimer); disconnectTimer = null; }
      stableConnected = true;
    } else {
      disconnectTimer = setTimeout(() => { stableConnected = false; }, 2000);
    }
  });
  onDestroy(() => { if (disconnectTimer) clearTimeout(disconnectTimer); });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="panel" onkeydown={handleGlobalKeydown}>
  <div class="topbar">
    <button class="back-btn" onclick={onBack} aria-label="back" data-tip="back">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
    <div class="topbar-info">
      <span class="title">{name}</span>
      <span class="dot" class:connected={stableConnected} class:thinking title={!stableConnected ? "disconnected" : thinking ? (boxStateVal === "tool_use" ? "using a tool" : "thinking") : "connected"}></span>
    </div>
    <button class="tool-toggle" class:active={showTools} onclick={() => { showTools = !showTools; tick().then(() => { if (outputEl) outputEl.scrollTop = outputEl.scrollHeight; }); }} aria-label="show tool activity" data-tip={showTools ? "hide tools" : "show tools"}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>
      </svg>
    </button>
  </div>

  <div class="output" class:no-anim={suppressAnim} bind:this={outputEl} onscroll={scroller.check} onclick={(e) => { const a = (e.target as HTMLElement).closest("a"); if (a?.href) { e.preventDefault(); openUrl(a.href); } }}>
    {#each lines as line (line.id)}
      {#if (line.kind !== "tool" && line.kind !== "notification") || showTools}
        <div class="line {line.kind}"><span class="ts">{line.time}</span>{@html linkify(line.text)}</div>
      {/if}
    {/each}
    {#if thinking && lines.length > 0}
      <div class="line thinking-indicator"><span></span><span></span><span></span></div>
    {/if}
    {#if lines.length === 0}
      <div class="empty-state">
        <div class="empty-dots"><span></span><span></span><span></span></div>
        <span class="empty-label">{connectedVal ? `${name} is listening. say something.` : "connecting..."}</span>
      </div>
    {/if}
  </div>

  <div class="reconnect-bar" class:visible={!connectedVal && wasConnected}>reconnecting...</div>

  <form class="input-bar" onsubmit={(e) => { e.preventDefault(); handleSend(); }}>
    <span class="prompt-char">&gt;</span>
    <textarea
      rows="1"
      placeholder={connectedVal ? "send a message..." : "connecting..."}
      bind:value={input}
      bind:this={inputEl}
      disabled={!connectedVal}
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

  .dot.connected.thinking {
    background: #ffa726;
    box-shadow: 0 0 6px rgba(255, 167, 38, 0.4);
  }

  .tool-toggle {
    margin-left: auto;
    background: transparent;
    border: none;
    color: rgba(255, 255, 255, 0.25);
    cursor: pointer;
    min-width: 44px;
    min-height: 44px;
    padding: 0;
    border-radius: 8px;
    corner-shape: squircle;
    transition: all 0.2s var(--spring);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .tool-toggle:hover {
    color: rgba(255, 255, 255, 0.5);
    background: rgba(255, 255, 255, 0.05);
  }

  .tool-toggle:active {
    transform: scale(0.95);
  }

  .tool-toggle.active {
    color: rgba(255, 255, 255, 0.7);
    background: rgba(255, 255, 255, 0.08);
  }

  .ts {
    color: rgba(255, 255, 255, 0.2);
    margin-right: 8px;
    font-size: 11px;
    user-select: none;
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
    padding: 0;
    max-height: 0;
    overflow: hidden;
    font-size: 11px;
    color: rgba(255, 200, 100, 0.8);
    background: rgba(255, 200, 100, 0.06);
    border-top: 1px solid transparent;
    text-align: center;
    user-select: none;
    opacity: 0;
    transition: max-height 0.2s var(--spring), opacity 0.2s var(--spring), padding 0.2s var(--spring), border-color 0.2s var(--spring);
  }

  .reconnect-bar.visible {
    padding: 6px 20px;
    max-height: 40px;
    opacity: 1;
    border-top-color: rgba(255, 200, 100, 0.1);
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
    padding: 0;
    margin: 0;
    overflow-y: auto;
    font-family: "SF Mono", "Fira Code", "JetBrains Mono", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.4;
    color: rgba(255, 255, 255, 0.75);
    caret-color: rgba(255, 255, 255, 0.4);
    max-height: 120px;
  }

  .input-bar textarea::-webkit-scrollbar { width: 4px; }
  .input-bar textarea::-webkit-scrollbar-track { background: transparent; }
  .input-bar textarea::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 2px; }

  .input-bar textarea::placeholder { color: rgba(255, 255, 255, 0.35); }
  .input-bar textarea:disabled { opacity: 0.25; cursor: not-allowed; }
  .input-bar textarea:focus-visible { box-shadow: none !important; }

  .input-bar:has(textarea:focus-visible) {
    border-top-color: rgba(255, 255, 255, 0.12);
  }
</style>
