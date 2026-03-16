<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { getVersion } from "@tauri-apps/api/app";
  import { listBoxes, startBox, stopBox, restartBox, deleteBox, backupBox, restoreBox } from "../lib/api";
  import { getBoxOp, setBoxOp, clearBoxOp, busyBoxName } from "../lib/store.svelte";
  import { save, open } from "@tauri-apps/plugin-dialog";
  import { createBoxConnection, type BoxConnection } from "../lib/ws";
  import type { ListEntry, BoxActivityState } from "../lib/types";

  let appVersion = $state("");

  let {
    onSelect,
    onCreate,
    onChat,
    onConsole,
  }: {
    onSelect: (name: string, wsPort: number, activity: BoxActivityState) => void;
    onCreate: () => void;
    onChat: (name: string, wsPort: number, activity: BoxActivityState) => void;
    onConsole: (name: string, wsPort: number, activity: BoxActivityState) => void;
  } = $props();

  let boxes = $state<ListEntry[]>([]);
  let poll: ReturnType<typeof setInterval>;
  let openMenu = $state<string | null>(null);
  let confirming = $state<string | null>(null);

  let connections = new Map<string, { conn: BoxConnection; unsub: () => void }>();
  let activityStates = $state<Record<string, BoxActivityState>>({});

  function syncConnections() {
    const aliveNames = new Set(boxes.filter((b) => b.alive).map((b) => `${b.name}:${b.ws_port}`));

    for (const [key, entry] of connections) {
      if (!aliveNames.has(key)) {
        entry.unsub();
        entry.conn.disconnect();
        connections.delete(key);
        const boxName = key.split(":")[0];
        const { [boxName]: _, ...rest } = activityStates;
        activityStates = rest;
      }
    }

    for (const box of boxes) {
      const key = `${box.name}:${box.ws_port}`;
      if (box.alive && !connections.has(key)) {
        const conn = createBoxConnection(box.ws_port);
        const unsub = conn.boxState.subscribe((v: BoxActivityState) => {
          if (activityStates[box.name] !== v) activityStates[box.name] = v;
        });
        conn.connect();
        connections.set(key, { conn, unsub });
      }
    }
  }

  function teardownConnections() {
    for (const [, entry] of connections) {
      entry.unsub();
      entry.conn.disconnect();
    }
    connections.clear();
  }

  async function refresh() {
    try {
      const next = await listBoxes();
      if (JSON.stringify(next) !== JSON.stringify(boxes)) {
        boxes = next;
        syncConnections();
      }
    } catch (e) {
      console.warn("failed to list boxes:", e);
    }
  }

  onMount(async () => {
    refresh();
    poll = setInterval(refresh, 5000);
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onKeydown);
    appVersion = await getVersion();
  });

  onDestroy(() => {
    clearInterval(poll);
    teardownConnections();
    document.removeEventListener("click", onDocClick);
    document.removeEventListener("keydown", onKeydown);
  });

  function onDocClick(e: MouseEvent) {
    if (openMenu && !(e.target as Element)?.closest?.(".menu-wrapper")) {
      openMenu = null;
      confirming = null;
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && openMenu) {
      openMenu = null;
      confirming = null;
    }
  }

  function orbClass(box: ListEntry, activity?: BoxActivityState): string {
    if (box.status === "dead") return "dead";
    if (box.status === "running" && box.authenticated && box.agent_ready) {
      if (activity === "thinking" || activity === "tool_use") return "active";
      return "alive";
    }
    if (box.status === "running" && box.authenticated) return "booting";
    if (box.status === "running" && !box.authenticated) return "auth";
    return "dead";
  }

  async function handleToggle(box: ListEntry) {
    if (busyBoxName()) return;
    setBoxOp(box.name, box.status === "running" ? "stopping" : "starting");
    try {
      if (box.status === "running") {
        await stopBox(box.name);
      } else {
        await startBox(box.name);
      }
      await refresh();
    } catch (e) {
      console.warn("toggle failed:", e);
    } finally {
      clearBoxOp(box.name);
    }
  }

  async function handleRestart(box: ListEntry) {
    if (busyBoxName()) return;
    setBoxOp(box.name, "starting");
    try {
      await restartBox(box.name);
      await refresh();
    } catch (e) {
      console.warn("restart failed:", e);
    } finally {
      clearBoxOp(box.name);
    }
  }

  async function handleBackup(box: ListEntry) {
    const date = new Date().toISOString().slice(0, 10);
    const path = await save({
      defaultPath: `${box.name}-backup-${date}.tar.gz`,
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
    });
    if (!path) return;
    setBoxOp(box.name, "backing-up");
    try {
      await backupBox(box.name, path);
      await refresh();
    } catch (e) {
      console.warn("backup failed:", e);
    } finally {
      clearBoxOp(box.name);
    }
  }

  async function handleRestore(box: ListEntry) {
    const path = await open({
      filters: [{ name: "Backup", extensions: ["tar.gz"] }],
      multiple: false,
      directory: false,
    });
    if (!path) return;
    setBoxOp(box.name, "restoring");
    try {
      await restoreBox(path, box.name, true);
      await refresh();
    } catch (e) {
      console.warn("restore failed:", e);
    } finally {
      clearBoxOp(box.name);
    }
  }

  async function handleDelete(boxName: string) {
    if (confirming !== boxName) {
      confirming = boxName;
      return;
    }
    setBoxOp(boxName, "deleting");
    confirming = null;
    try {
      await deleteBox(boxName);
      await refresh();
    } catch (e) {
      console.warn("delete failed:", e);
    } finally {
      clearBoxOp(boxName);
    }
  }

  function menuAction(fn: () => void) {
    return (e: MouseEvent) => { e.stopPropagation(); openMenu = null; fn(); };
  }

  let gridCols = $derived(boxes.length === 1 ? 1 : boxes.length === 2 ? 2 : 3);

  function isBoxBusy(boxName: string): boolean {
    return getBoxOp(boxName).operation !== "idle";
  }
</script>

<div class="grid-view" class:centered={gridCols < 3}>
  <button class="add-btn" onclick={onCreate} aria-label="new box" data-tip="new box">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
      <path d="M12 5v14M5 12h14"/>
    </svg>
  </button>
  <div class="grid cols-{gridCols}" class:few={gridCols < 3}>
    {#each boxes as box}
      <div class="card-wrapper">
        <button class="card" class:busy={isBoxBusy(box.name)} onclick={() => onSelect(box.name, box.ws_port, activityStates[box.name] ?? "idle")}>
          <div class="mini-orb-container {orbClass(box, activityStates[box.name])}">
            <div class="mini-orb-glow"></div>
            <div class="mini-orb-body">
              <div class="mini-orb-highlight"></div>
            </div>
          </div>
          <span class="card-name">{box.name}</span>
        </button>
        <div class="menu-wrapper">
          <!-- svelte-ignore a11y_click_events_have_key_events -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="menu-trigger"
            class:visible={openMenu === box.name}
            onclick={(e) => { e.stopPropagation(); openMenu = openMenu === box.name ? null : box.name; confirming = null; }}
            aria-label="more options"
            data-tip="actions"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor">
              <circle cx="8" cy="3" r="1.5"/>
              <circle cx="8" cy="8" r="1.5"/>
              <circle cx="8" cy="13" r="1.5"/>
            </svg>
          </div>
          {#if openMenu === box.name}
            <div class="menu-dropdown">
              {#if confirming === box.name}
                <button class="menu-item danger" onclick={menuAction(() => handleDelete(box.name))}>confirm delete</button>
                <button class="menu-item muted" onclick={menuAction(() => { confirming = null; })}>cancel</button>
              {:else}
                {#if box.alive}
                  <button class="menu-item" onclick={menuAction(() => onChat(box.name, box.ws_port, activityStates[box.name] ?? "idle"))}>chat</button>
                  <button class="menu-item" onclick={menuAction(() => onConsole(box.name, box.ws_port, activityStates[box.name] ?? "idle"))}>console</button>
                {/if}
                <button class="menu-item" disabled={!!busyBoxName()} onclick={menuAction(() => handleToggle(box))}>{box.status === "running" ? "stop" : "start"}</button>
                {#if box.status === "running"}
                  <button class="menu-item" disabled={!!busyBoxName()} onclick={menuAction(() => handleRestart(box))}>restart</button>
                {/if}
                <button class="menu-item" disabled={!!busyBoxName()} onclick={menuAction(() => handleBackup(box))}>backup</button>
                <button class="menu-item" disabled={!!busyBoxName()} onclick={menuAction(() => handleRestore(box))}>load backup</button>
                <div class="menu-divider"></div>
                <button class="menu-item danger" disabled={!!busyBoxName()} onclick={(e: MouseEvent) => { e.stopPropagation(); handleDelete(box.name); }}>delete</button>
              {/if}
            </div>
          {/if}
        </div>
      </div>
    {/each}
  </div>
  {#if appVersion}
    <span class="version">v{appVersion}</span>
  {/if}
</div>

<style>
  .grid-view {
    position: relative;
    width: 100%;
    height: 100%;
    padding: 8px 12px 8px;
    overflow-y: auto;
    animation: viewIn 0.6s var(--spring);
  }

  .grid-view.centered {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }

  .grid-view::-webkit-scrollbar { width: 6px; }
  .grid-view::-webkit-scrollbar-track { background: transparent; }
  .grid-view::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.08); border-radius: 3px; }

  @keyframes viewIn {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }

  .add-btn {
    position: absolute;
    top: 4px;
    right: 8px;
    z-index: 10;
    width: 44px;
    height: 44px;
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 8px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.7);
    color: #5a5450;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s var(--spring-bouncy);
  }

  .add-btn:hover {
    background: rgba(255, 255, 255, 0.95);
    border-color: rgba(0, 0, 0, 0.12);
    color: #1a1816;
    transform: translateY(-1px);
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  }

  .add-btn:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .grid {
    display: grid;
    gap: 8px;
    width: 100%;
    padding-top: 40px;
    grid-template-columns: repeat(3, 1fr);
  }

  .grid.few {
    padding-top: 0;
  }

  .grid.cols-1 {
    grid-template-columns: 1fr;
    max-width: 220px;
    margin: 0 auto;
  }

  .grid.cols-2 {
    grid-template-columns: repeat(2, 1fr);
    max-width: 440px;
    margin: 0 auto;
  }

  .card-wrapper {
    position: relative;
  }

  .card {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 4px;
    width: 100%;
    aspect-ratio: 1;
    border: 1px solid rgba(0, 0, 0, 0.06);
    border-radius: 12px;
    corner-shape: squircle;
    background: rgba(255, 255, 255, 0.5);
    cursor: pointer;
    transition: all 0.2s var(--spring-bouncy);
    font-family: inherit;
    padding: 8px 4px;
  }

  .card:hover {
    background: rgba(255, 255, 255, 0.8);
    border-color: rgba(0, 0, 0, 0.1);
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  }

  .card:active {
    transform: scale(0.97);
    box-shadow: none;
  }

  .card.busy {
    opacity: 0.5;
    pointer-events: none;
  }

  /* Show menu trigger on card hover */
  .card-wrapper:hover .menu-trigger,
  .menu-trigger.visible {
    opacity: 1;
  }

  /* --- Mini Orb --- */
  .mini-orb-container {
    position: relative;
    width: 36px;
    height: 36px;
    transition: filter 0.8s var(--spring), width 0.3s var(--spring), height 0.3s var(--spring);
  }

  .cols-1 .mini-orb-container {
    width: 56px;
    height: 56px;
  }

  .cols-2 .mini-orb-container {
    width: 44px;
    height: 44px;
  }

  .mini-orb-body {
    position: absolute;
    inset: 6px;
    border-radius: 50%;
    background: radial-gradient(circle at 38% 32%, #b8ceb0, #7a9e70 50%, #5a7e50);
    box-shadow:
      inset 0 -3px 8px rgba(0, 0, 0, 0.15),
      inset 0 2px 4px rgba(255, 255, 255, 0.15);
    transition: background 0.8s var(--spring), box-shadow 0.8s var(--spring);
  }

  .mini-orb-highlight {
    position: absolute;
    top: 18%;
    left: 28%;
    width: 28%;
    height: 20%;
    border-radius: 50%;
    background: radial-gradient(ellipse, rgba(255, 255, 255, 0.55), transparent);
    filter: blur(1px);
    transition: opacity 0.8s var(--spring);
  }

  .mini-orb-glow {
    position: absolute;
    inset: -2px;
    border-radius: 50%;
    background: radial-gradient(circle, rgba(138, 180, 120, 0.35), transparent 70%);
    filter: blur(6px);
    transition: opacity 0.8s var(--spring), background 0.8s var(--spring);
  }

  /* Alive */
  .mini-orb-container.alive {
    animation: float 4s ease-in-out infinite;
  }

  .mini-orb-container.alive .mini-orb-glow {
    animation: glow-pulse 3s ease-in-out infinite;
  }

  .mini-orb-container.alive .mini-orb-body {
    animation: orb-breathe 3s ease-in-out infinite;
  }

  /* Active — thinking / tool use (amber) */
  .mini-orb-container.active {
    animation: float 2s ease-in-out infinite;
  }

  .mini-orb-container.active .mini-orb-body {
    background: radial-gradient(circle at 38% 32%, #e8d0a0, #c4a060 50%, #a08040);
    animation: orb-breathe 1.2s ease-in-out infinite;
  }

  .mini-orb-container.active .mini-orb-glow {
    background: radial-gradient(circle, rgba(200, 170, 100, 0.4), transparent 70%);
    animation: glow-pulse 1.2s ease-in-out infinite;
  }

  /* Booting — alive but WS not ready */
  .mini-orb-container.booting {
    animation: float 3s ease-in-out infinite;
  }

  .mini-orb-container.booting .mini-orb-body {
    background: radial-gradient(circle at 38% 32%, #c4deb8, #8ab880 50%, #6a9e5a);
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .mini-orb-container.booting .mini-orb-glow {
    animation: glow-swell 1.5s ease-in-out infinite;
  }

  /* Auth — running but not signed in */
  .mini-orb-container.auth {
    animation: float 3s ease-in-out infinite;
  }

  .mini-orb-container.auth .mini-orb-body {
    background: radial-gradient(circle at 38% 32%, #c0d0e8, #80a0c4 50%, #6080a4);
    animation: orb-breathe 2s ease-in-out infinite;
  }

  .mini-orb-container.auth .mini-orb-glow {
    background: radial-gradient(circle, rgba(100, 150, 200, 0.35), transparent 70%);
    animation: glow-pulse 2s ease-in-out infinite;
  }

  /* Dead / Stopped */
  .mini-orb-container.dead .mini-orb-body {
    background: radial-gradient(circle at 38% 32%, #c4bdb5, #a09890 50%, #8b7e74);
    box-shadow:
      inset 0 -3px 8px rgba(0, 0, 0, 0.1),
      inset 0 2px 4px rgba(255, 255, 255, 0.05);
    transform: scale(0.92);
  }

  .mini-orb-container.dead .mini-orb-glow {
    opacity: 0.15;
    background: radial-gradient(circle, rgba(160, 152, 144, 0.2), transparent 70%);
  }

  .mini-orb-container.dead .mini-orb-highlight {
    opacity: 0.3;
  }

  @keyframes float {
    0%, 100% { translate: 0 0; }
    50% { translate: 0 -2px; }
  }

  @keyframes glow-pulse {
    0%, 100% { opacity: 0.7; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.08); }
  }

  @keyframes orb-breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.03); }
  }

  @keyframes glow-swell {
    0%, 100% { opacity: 0.4; transform: scale(1); }
    50% { opacity: 1; transform: scale(1.12); }
  }

  .card-name {
    font-size: 11px;
    font-weight: 550;
    color: #3d3a36;
    letter-spacing: -0.01em;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    user-select: none;
  }

  .cols-1 .card-name {
    font-size: 14px;
  }

  .cols-2 .card-name {
    font-size: 12px;
  }

  /* --- Three-dot menu --- */
  .menu-wrapper {
    position: absolute;
    top: 4px;
    right: 4px;
  }

  .menu-trigger {
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    corner-shape: squircle;
    cursor: pointer;
    color: #a09890;
    opacity: 0;
    transition: opacity 0.15s ease, background 0.12s ease, color 0.12s ease;
  }

  .menu-trigger:hover {
    background: rgba(0, 0, 0, 0.06);
    color: #5a5450;
  }

  .menu-dropdown {
    position: absolute;
    top: calc(100% + 4px);
    right: 0;
    display: flex;
    flex-direction: column;
    min-width: 120px;
    background: rgba(255, 255, 255, 0.85);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(0, 0, 0, 0.08);
    border-radius: 10px;
    corner-shape: squircle;
    padding: 4px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
    animation: menuIn 0.15s var(--spring);
    z-index: 20;
  }

  @keyframes menuIn {
    from { opacity: 0; transform: translateY(-4px) scale(0.96); }
    to { opacity: 1; transform: translateY(0) scale(1); }
  }

  .menu-divider {
    height: 1px;
    background: rgba(0, 0, 0, 0.06);
    margin: 2px 8px;
  }

  .menu-item {
    padding: 8px 12px;
    min-height: 32px;
    border: none;
    background: transparent;
    font-family: inherit;
    font-size: 12px;
    font-weight: 500;
    color: #5a5450;
    cursor: pointer;
    border-radius: 6px;
    corner-shape: squircle;
    text-align: left;
    transition: background 0.12s ease;
    display: flex;
    align-items: center;
  }

  .menu-item:hover {
    background: rgba(0, 0, 0, 0.05);
  }

  .menu-item.danger {
    color: #c45450;
  }

  .menu-item.danger:hover {
    background: rgba(196, 84, 80, 0.08);
  }

  .menu-item.muted {
    color: #a09890;
  }

  .menu-item:disabled {
    opacity: 0.25;
    cursor: not-allowed;
    pointer-events: none;
  }

  .version {
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    font-size: 10px;
    font-weight: 400;
    letter-spacing: 0.02em;
    color: #c4bdb5;
    user-select: none;
    pointer-events: none;
  }

  @media (prefers-color-scheme: dark) {
    .grid-view::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.08); }

    .add-btn {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.06);
      color: #b0a8a0;
    }
    .add-btn:hover {
      background: rgba(255, 255, 255, 0.14);
      border-color: rgba(255, 255, 255, 0.1);
      color: #e8e0d8;
      box-shadow: 0 2px 12px rgba(0, 0, 0, 0.2);
    }

    .card {
      background: rgba(255, 255, 255, 0.04);
      border-color: rgba(255, 255, 255, 0.06);
    }

    .card:hover {
      background: rgba(255, 255, 255, 0.08);
      border-color: rgba(255, 255, 255, 0.1);
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
    }

    .card-name {
      color: #e8e0d8;
    }

    .menu-trigger {
      color: #6a625a;
    }
    .menu-trigger:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #a09890;
    }

    .menu-dropdown {
      background: rgba(40, 38, 36, 0.9);
      border-color: rgba(255, 255, 255, 0.08);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }

    .menu-item {
      color: #b0a8a0;
    }
    .menu-item:hover {
      background: rgba(255, 255, 255, 0.08);
      color: #e8e0d8;
    }
    .menu-item.danger {
      color: #e07070;
    }
    .menu-item.danger:hover {
      background: rgba(224, 112, 112, 0.1);
      color: #f08080;
    }
    .menu-item.muted {
      color: #8a8078;
    }
    .menu-divider {
      background: rgba(255, 255, 255, 0.06);
    }
    .version {
      color: #5a5450;
    }
  }
</style>
