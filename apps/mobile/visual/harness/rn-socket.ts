import type { SocketLike } from "@vesta/core";
import { visualSwitch } from "./launch-query";

// The chat socket without a gateway: it opens on the next tick, and
// visualLive=typing streams long replies after open in two batches of three,
// so the paced queue (which flushes past three pending) shows the typing
// indicator continuously for well over the capture window.
const liveVariant = visualSwitch("visualLive");
const TYPING_REPLIES = Array.from({ length: 6 }, (_, index) => ({
  id: 9001 + index,
  type: "chat",
  text: `Update ${index + 1}: first the visual regressions, then the demo notes, then the follow-ups from the launch thread. I will keep the checklist updated as each one lands, and flag anything that needs a decision from you before the review.`,
  ts: `2026-08-01T09:2${4 + index}:00.000Z`,
}));

export function createRnSocket(_url: string): SocketLike {
  const adapter: SocketLike = {
    send: () => undefined,
    close: () => undefined,
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  setTimeout(() => {
    adapter.onopen?.();
    if (liveVariant === "typing") {
      const send = (replies: typeof TYPING_REPLIES) => {
        for (const reply of replies) adapter.onmessage?.(JSON.stringify(reply));
      };
      setTimeout(() => send(TYPING_REPLIES.slice(0, 3)), 400);
      setTimeout(() => send(TYPING_REPLIES.slice(3)), 15_000);
    }
  }, 0);
  return adapter;
}
