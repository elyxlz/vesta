import { tick } from "svelte";

export function createAutoScroller(getEl: () => HTMLElement | undefined) {
  let wasNearBottom = true;

  function check() {
    const el = getEl();
    if (!el) return;
    wasNearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
  }

  async function scroll() {
    if (!wasNearBottom) return;
    await tick();
    const el = getEl();
    if (el) el.scrollTop = el.scrollHeight;
  }

  return { check, scroll };
}
