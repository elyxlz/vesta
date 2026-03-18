<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { streamLogs, stopLogs } from "../lib/api";
  import { stripAnsi } from "../lib/ansi";
  import { linkify } from "../lib/linkify";
  import { createAutoScroller } from "../lib/scroll";
  import "../styles/panel.css";
  import type { LogEvent } from "../lib/types";

  let { name, onBack }: { name: string; onBack: () => void } = $props();

  type Line = { id: number; text: string };
  let lines = $state<Line[]>([]);
  let nextId = 0;
  let outputEl: HTMLDivElement;

  const scroller = createAutoScroller(() => outputEl);

  const MAX_LINES = 5000;

  let streamEnded = $state(false);
  let suppressAnim = $state(true);

  function addLine(text: string) {
    const cleaned = stripAnsi(text).trimEnd();
    lines.push({ id: nextId++, text: cleaned });
    if (lines.length > MAX_LINES) lines.splice(0, lines.length - MAX_LINES);
    lines = lines;
    scroller.scroll();
  }

  let alive = true;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;
  let retryDelay = 1000;
  const RETRY_MAX = 30000;

  function scheduleRetry() {
    streamEnded = true;
    if (!alive) return;
    if (retryTimer) clearTimeout(retryTimer);
    retryTimer = setTimeout(startStream, retryDelay);
    retryDelay = Math.min(retryDelay * 2, RETRY_MAX);
  }

  async function startStream() {
    streamEnded = false;
    try {
      await streamLogs(name, (ev: LogEvent) => {
        if (!alive) return;
        if (ev.kind === "Line") { retryDelay = 1000; addLine(ev.text); }
        if (ev.kind === "Error") addLine(`error: ${ev.message}`);
        if (ev.kind === "End") scheduleRetry();
      });
    } catch (e) {
      console.error("streamLogs failed:", e);
      scheduleRetry();
    }
  }

  onMount(() => {
    requestAnimationFrame(() => { suppressAnim = false; });
    startStream();
  });

  onDestroy(() => {
    alive = false;
    if (retryTimer) clearTimeout(retryTimer);
    stopLogs(name).catch(() => {});
  });

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") onBack();
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="panel" onkeydown={handleKeydown}>
  <div class="topbar">
    <button class="back-btn" onclick={onBack} aria-label="back" data-tip="back">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <polyline points="15 18 9 12 15 6"/>
      </svg>
    </button>
    <div class="topbar-info">
      <span class="title">{name}</span>
    </div>
  </div>

  <div class="output" class:no-anim={suppressAnim} bind:this={outputEl} onscroll={scroller.check}>
    {#each lines as line (line.id)}
      <div class="line">{@html linkify(line.text)}</div>
    {/each}
    {#if streamEnded}
      <div class="line stream-ended">— reconnecting —</div>
    {/if}
    {#if lines.length === 0 && !streamEnded}
      <div class="empty-state">
        <div class="empty-dots"><span></span><span></span><span></span></div>
        <span class="empty-label">streaming logs...</span>
      </div>
    {/if}
  </div>
</div>

<style>
  .back-btn {
    corner-shape: squircle;
  }

  .stream-ended {
    color: rgba(255, 255, 255, 0.25);
    font-family: "Inter", -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 12px;
    text-align: center;
    padding: 8px 0;
  }
</style>
