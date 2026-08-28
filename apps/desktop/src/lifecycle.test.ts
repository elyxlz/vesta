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
  it("starts not quitting", () => {
    const app = fakeApp();
    const isQuitting = trackQuitIntent(app);
    expect(isQuitting()).toBe(false);
  });

  it("flips on before-quit", () => {
    const app = fakeApp();
    const isQuitting = trackQuitIntent(app);
    app.emit("before-quit");
    expect(isQuitting()).toBe(true);
  });

  it("flips on before-quit-for-update, so an update relaunch lifts the macOS close guard", () => {
    const app = fakeApp();
    const isQuitting = trackQuitIntent(app);
    app.emit("before-quit-for-update");
    expect(isQuitting()).toBe(true);
  });
});
