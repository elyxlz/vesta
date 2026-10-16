import type { AudioCapture } from "./engine-session";

// The one owner of a stop that comes while the microphone starts. A start waits until the start
// before it settles, and a start that a stop overtook is stopped again once it settles, so a
// port only turns the microphone on in start and off in stop.
export function serializeCapture(port: AudioCapture): AudioCapture {
  // Bumped by every start and stop: a start that is no longer the newest gives up.
  let attempt = 0;
  let settled: Promise<void> = Promise.resolve();
  return {
    start: (onFrame) => {
      const mine = ++attempt;
      const run = settled.then(async () => {
        if (mine !== attempt) return;
        try {
          await port.start(onFrame);
        } finally {
          if (mine !== attempt) port.stop();
        }
      });
      settled = run.catch(() => undefined);
      return run;
    },
    stop: () => {
      attempt += 1;
      port.stop();
    },
  };
}
