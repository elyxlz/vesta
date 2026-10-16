import { describe, expect, it } from "vitest";
import type { AudioCapture } from "./engine-session";
import { serializeCapture } from "./microphone";

// A port that turns the microphone on only when the test lets its start finish, and records
// each call in order.
function slowPort() {
  const calls: string[] = [];
  const opens: (() => void)[] = [];
  let on = false;
  const port: AudioCapture = {
    start: () =>
      new Promise((resolve) => {
        calls.push("start");
        opens.push(() => {
          on = true;
          resolve();
        });
      }),
    stop: () => {
      calls.push("stop");
      on = false;
    },
  };
  return {
    port,
    calls,
    finishStart: (index: number) => opens[index]?.(),
    isOn: () => on,
  };
}

const noFrames = (): void => undefined;

describe("serializeCapture", () => {
  it("turns the microphone off when a stop came while it was starting", async () => {
    const mic = slowPort();
    const capture = serializeCapture(mic.port);

    const started = capture.start(noFrames);
    await Promise.resolve();
    capture.stop();
    mic.finishStart(0);
    await started;

    expect(mic.isOn()).toBe(false);
    expect(mic.calls).toEqual(["start", "stop", "stop"]);
  });

  it("starts again only after the start before it settled, and keeps the new microphone on", async () => {
    const mic = slowPort();
    const capture = serializeCapture(mic.port);

    const first = capture.start(noFrames);
    await Promise.resolve();
    capture.stop();
    const second = capture.start(noFrames);
    await Promise.resolve();
    expect(mic.calls).toEqual(["start", "stop"]);

    mic.finishStart(0);
    await first;
    await Promise.resolve();
    mic.finishStart(1);
    await second;

    expect(mic.calls).toEqual(["start", "stop", "stop", "start"]);
    expect(mic.isOn()).toBe(true);
  });

  it("never starts a start that a stop overtook while it waited", async () => {
    const mic = slowPort();
    const capture = serializeCapture(mic.port);

    const first = capture.start(noFrames);
    await Promise.resolve();
    capture.stop();
    const second = capture.start(noFrames);
    capture.stop();
    mic.finishStart(0);
    await Promise.all([first, second]);

    expect(mic.calls).toEqual(["start", "stop", "stop", "stop"]);
    expect(mic.isOn()).toBe(false);
  });

  it("passes a failed start on and still lets the next start run", async () => {
    const calls: string[] = [];
    let fail = true;
    const capture = serializeCapture({
      start: () => {
        calls.push("start");
        return fail ? Promise.reject(new Error("denied")) : Promise.resolve();
      },
      stop: () => {
        calls.push("stop");
      },
    });

    await expect(capture.start(noFrames)).rejects.toThrow("denied");
    fail = false;
    await capture.start(noFrames);

    expect(calls).toEqual(["start", "start"]);
  });
});
