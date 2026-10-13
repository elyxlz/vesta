import { describe, expect, it, vi } from "vitest";

import {
  PLAY_START_TIMEOUT_MS,
  createPlayQueue,
  type PlayReport,
} from "./play-queue";
import { fakeSpeaker } from "./voice-fakes";

function setup() {
  const { speaker, plays, urls, calls } = fakeSpeaker();
  const reports: [string, PlayReport][] = [];
  const speaking: boolean[] = [];
  const errors: string[] = [];
  const queue = createPlayQueue({
    speaker,
    resolveUrl: (path) => Promise.resolve(`https://host${path}`),
    report: (id, state) => reports.push([id, state]),
    onSpeakingChange: (value) => speaking.push(value),
    onError: (message) => errors.push(message),
  });
  const playing = async (count: number) => {
    await vi.waitFor(() => {
      expect(plays).toHaveLength(count);
    });
  };
  return { queue, plays, urls, calls, reports, speaking, errors, playing };
}

describe("the play queue", () => {
  it("plays each play in arrival order and reports what the speaker did", async () => {
    const { queue, plays, urls, reports, speaking, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    queue.enqueue("b", "/voice/play/tb");
    await playing(1);
    expect(urls()).toEqual(["https://host/voice/play/ta"]);
    expect(reports).toEqual([]);

    plays[0]?.started();
    plays[0]?.finish();
    await playing(2);
    plays[1]?.started();
    plays[1]?.finish();
    await vi.waitFor(() => {
      expect(queue.speaking()).toBe(false);
    });

    expect(reports).toEqual([
      ["a", "started"],
      ["a", "finished"],
      ["b", "started"],
      ["b", "finished"],
    ]);
    expect(speaking).toEqual([true, false]);
  });

  it("reports a play the speaker cannot play as failed and continues", async () => {
    const { queue, plays, reports, errors, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    queue.enqueue("b", "/voice/play/tb");
    await playing(1);
    plays[0]?.fail();
    await playing(2);

    expect(reports).toEqual([["a", "failed"]]);
    expect(errors).toEqual(["Voice playback failed"]);
  });

  it("a stop ends the audio, drops the queue, and reports nothing", async () => {
    const { queue, plays, reports, speaking, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    queue.enqueue("b", "/voice/play/tb");
    await playing(1);
    plays[0]?.started();

    queue.stop();
    await Promise.resolve();

    expect(queue.speaking()).toBe(false);
    expect(plays).toHaveLength(1);
    expect(reports).toEqual([["a", "started"]]);
    expect(speaking).toEqual([true, false]);
  });

  it("the plays after a stop all play, in order", async () => {
    const { queue, plays, urls, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    await playing(1);
    queue.stop();
    queue.enqueue("b", "/voice/play/tb");
    queue.enqueue("c", "/voice/play/tc");
    await playing(2);
    plays[1]?.finish();
    await playing(3);

    expect(urls()).toEqual([
      "https://host/voice/play/ta",
      "https://host/voice/play/tb",
      "https://host/voice/play/tc",
    ]);
  });

  it("hands a pause and a resume to the speaker while a play is on it", async () => {
    const { queue, calls, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    await playing(1);
    queue.pause();
    queue.resume();
    expect(calls).toEqual(["pause", "resume"]);
  });

  it("a pause between two plays holds the next play until the resume", async () => {
    const { queue, plays, calls, reports, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    queue.enqueue("b", "/voice/play/tb");
    await playing(1);
    plays[0]?.started();
    queue.pause();
    plays[0]?.finish();
    await vi.waitFor(() => {
      expect(reports).toEqual([
        ["a", "started"],
        ["a", "finished"],
      ]);
    });
    await Promise.resolve();
    expect(plays).toHaveLength(1);

    queue.resume();
    await playing(2);
    // The second play was not on the speaker during the pause, so only the first one
    // was paused there.
    expect(calls).toEqual(["pause"]);
  });

  it("a stop during a pause ends the pause, and a resume after it reaches no speaker", async () => {
    const { queue, plays, calls, urls, playing } = setup();
    queue.enqueue("a", "/voice/play/ta");
    await playing(1);
    plays[0]?.started();
    queue.pause();
    queue.stop();
    queue.resume();
    expect(calls).toEqual(["pause"]);

    queue.enqueue("b", "/voice/play/tb");
    await playing(2);
    expect(urls().at(-1)).toBe("https://host/voice/play/tb");
  });

  it("gives up a play whose sound never starts, and plays the next one", async () => {
    vi.useFakeTimers();
    try {
      const { queue, plays, reports, errors } = setup();
      queue.enqueue("a", "/voice/play/ta");
      queue.enqueue("b", "/voice/play/tb");
      await vi.advanceTimersByTimeAsync(0);
      expect(plays).toHaveLength(1);

      await vi.advanceTimersByTimeAsync(PLAY_START_TIMEOUT_MS);

      expect(reports).toEqual([["a", "failed"]]);
      expect(errors).toEqual(["Voice playback failed"]);
      expect(plays).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("a play whose sound started is never given up", async () => {
    vi.useFakeTimers();
    try {
      const { queue, plays, reports } = setup();
      queue.enqueue("a", "/voice/play/ta");
      await vi.advanceTimersByTimeAsync(0);
      plays[0]?.started();
      await vi.advanceTimersByTimeAsync(PLAY_START_TIMEOUT_MS * 2);
      expect(reports).toEqual([["a", "started"]]);
    } finally {
      vi.useRealTimers();
    }
  });
});
