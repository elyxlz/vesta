import { tick } from "svelte";

export function createAutoScroller(getEl: () => HTMLElement | undefined) {
  let wasNearBottom = true;
  return {
    check() {
      const el = getEl();
      if (!el) return;
      wasNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    },
    scroll() {
      tick().then(() => {
        const el = getEl();
        if (el && wasNearBottom) el.scrollTop = el.scrollHeight;
      });
    },
  };
}
