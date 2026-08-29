import { describe, expect, it } from "vitest";
import { trackQuitIntent } from "./lifecycle";

function fakeApp() {
  const handlers: Record<string, () => void> = {};
  return {
    on(event: string, listener: () => void): void {
      handlers[event] = listener;
    },
    emit(event: string): void {
      handlers[event]?.();
    },
  };
}

describe("trackQuitIntent", () => {
  // `before-quit-for-update` is the update relaunch, and it must lift the macOS close guard too.
  it.each(["before-quit", "before-quit-for-update"])(
    "flips from not-quitting to quitting on %s",
    (event) => {
      const app = fakeApp();
      const isQuitting = trackQuitIntent(app);
      expect(isQuitting()).toBe(false);
      app.emit(event);
      expect(isQuitting()).toBe(true);
    },
  );
});
