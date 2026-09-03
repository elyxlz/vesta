import { describe, expect, it, vi } from "vitest";

import { createTtsQueue, type SpeechPlayer } from "./tts-queue";

// A player that records prepare/play order and lets the test resolve each play by hand, so
// queue ordering and epoch invalidation are observed without a real audio stack.
function fakePlayer() {
  const prepared: string[] = [];
  const played: string[] = [];
  const resolvers: (() => void)[] = [];
  const player: SpeechPlayer = {
    prepare: (text) => {
      prepared.push(text);
      return Promise.resolve(`id:${text}`);
    },
    play: (id, signal) =>
      new Promise<void>((resolve, reject) => {
        played.push(id);
        resolvers.push(resolve);
        signal.addEventListener("abort", () => {
          reject(new Error("aborted"));
        });
      }),
  };
  return { player, prepared, played, finishNext: () => resolvers.shift()?.() };
}

describe("the TTS queue", () => {
  it("plays queued replies in order, one after another", async () => {
    const { player, played, finishNext } = fakePlayer();
    const queue = createTtsQueue(player, {});
    queue.speak("first");
    queue.speak("second");
    await vi.waitFor(() => {
      expect(played).toEqual(["id:first"]);
    });
    finishNext();
    await vi.waitFor(() => {
      expect(played).toEqual(["id:first", "id:second"]);
    });
  });

  it("reports speaking across the run and clears it when the queue drains", async () => {
    const { player, finishNext } = fakePlayer();
    const changes: boolean[] = [];
    const queue = createTtsQueue(player, {
      onSpeakingChange: (s) => changes.push(s),
    });
    queue.speak("only");
    await vi.waitFor(() => {
      expect(queue.speaking()).toBe(true);
    });
    finishNext();
    await vi.waitFor(() => {
      expect(queue.speaking()).toBe(false);
    });
    expect(changes).toEqual([true, false]);
  });

  it("drops the unplayed rest and ends speaking on stop", async () => {
    const { player, played } = fakePlayer();
    const queue = createTtsQueue(player, {});
    queue.speak("a");
    queue.speak("b");
    await vi.waitFor(() => {
      expect(played).toEqual(["id:a"]);
    });
    queue.stop();
    expect(queue.speaking()).toBe(false);
    await new Promise((r) => setTimeout(r, 0));
    expect(played).toEqual(["id:a"]);
  });

  it("reuses a prefetched id instead of preparing again", async () => {
    const { player, prepared, finishNext } = fakePlayer();
    const queue = createTtsQueue(player, {});
    queue.prefetch("warm");
    await vi.waitFor(() => {
      expect(prepared).toEqual(["warm"]);
    });
    queue.speak("warm");
    await vi.waitFor(() => {
      expect(queue.speaking()).toBe(true);
    });
    finishNext();
    expect(prepared).toEqual(["warm"]);
  });

  it("reports an error when a real playback failure occurs", async () => {
    const errors: string[] = [];
    const player: SpeechPlayer = {
      prepare: (t) => Promise.resolve(t),
      play: () => Promise.reject(new Error("decode failed")),
    };
    const queue = createTtsQueue(player, { onError: (m) => errors.push(m) });
    queue.speak("boom");
    await vi.waitFor(() => {
      expect(errors).toEqual(["Voice playback failed"]);
    });
    expect(queue.speaking()).toBe(false);
  });
});
