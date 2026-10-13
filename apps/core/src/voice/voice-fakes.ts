// Fakes for the voice tests: an engine socket the test drives, a microphone, and a speaker
// whose plays the test starts and ends by hand.

import { record } from "../protocol/parse";
import type { AudioCapture, VoiceSocketLike } from "./engine-session";
import type { Speaker } from "./play-queue";

export class FakeEngineSocket implements VoiceSocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onclose: ((reason: string) => void) | null = null;
  sent: (string | ArrayBuffer)[] = [];
  closed = false;
  send(data: string | ArrayBuffer): void {
    this.sent.push(data);
  }
  close(): void {
    this.closed = true;
  }
  // One frame from the engine.
  emit(frame: Record<string, unknown>): void {
    this.onmessage?.(JSON.stringify(frame));
  }
  // The engine accepted the session.
  accept(): void {
    this.onopen?.();
    this.emit({ type: "state", value: "listening" });
  }
  // The text frames the client sent, parsed.
  frames(): Record<string, unknown>[] {
    return this.sent
      .filter((data): data is string => typeof data === "string")
      .map((data) => record(JSON.parse(data)) ?? {});
  }
  audio(): ArrayBuffer[] {
    return this.sent.filter(
      (data): data is ArrayBuffer => typeof data !== "string",
    );
  }
}

// A capture port that hands the session an onFrame the test drives.
export function fakeCapture(): {
  capture: AudioCapture;
  send: (bytes: number) => void;
} {
  let frame: ((pcm: ArrayBuffer) => void) | null = null;
  const capture: AudioCapture = {
    start: (onFrame) => {
      frame = onFrame;
      return Promise.resolve();
    },
    stop: () => {
      frame = null;
    },
  };
  return { capture, send: (bytes) => frame?.(new ArrayBuffer(bytes)) };
}

interface FakePlay {
  url: string;
  started: () => void;
  finish: () => void;
  fail: () => void;
}

// A speaker that records each play and lets the test say when its sound starts, ends, or
// fails. An aborted play resolves, as a real speaker's does.
export function fakeSpeaker(): {
  speaker: Speaker;
  plays: FakePlay[];
  urls: () => string[];
  calls: string[];
} {
  const plays: FakePlay[] = [];
  const calls: string[] = [];
  const speaker: Speaker = {
    play: (url, signal, onStarted) =>
      new Promise<void>((resolve, reject) => {
        plays.push({
          url,
          started: onStarted,
          finish: resolve,
          fail: () => {
            reject(new Error("cannot play"));
          },
        });
        signal.addEventListener("abort", () => {
          resolve();
        });
      }),
    pause: () => {
      calls.push("pause");
    },
    resume: () => {
      calls.push("resume");
    },
  };
  return { speaker, plays, urls: () => plays.map((play) => play.url), calls };
}
