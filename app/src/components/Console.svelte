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

  function addLine(text: string) {
    const cleaned = stripAnsi(text).trimEnd();
    lines.push({ id: nextId++, text: cleaned });
    if (lines.length > MAX_LINES) lines.splice(0, lines.length - MAX_LINES);
    lines = lines;
    scroller.scroll();
  }

  let alive = true;

  onMount(async () => {
    try {
      await streamLogs((ev: LogEvent) => {
        if (!alive) return;
        if (ev.kind === "Line") addLine(ev.text);
        if (ev.kind === "Error") addLine(`error: ${ev.message}`);
        if (ev.kind === "End") streamEnded = true;
      });
    } catch (e) { console.error("streamLogs failed:", e); }
  });

  onDestroy(() => {
    alive = false;
    stopLogs().catch(() => {});
  });
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
    </div>
  </div>

  <div class="output" bind:this={outputEl} onscroll={scroller.check}>
    {#each lines as line (line.id)}
      <div class="line">{@html linkify(line.text)}</div>
    {/each}
    {#if streamEnded}
      <div class="line stream-ended">— stream ended —</div>
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
    font-style: italic;
    text-align: center;
    padding: 8px 0;
  }
</style>
