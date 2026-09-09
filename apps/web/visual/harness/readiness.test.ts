// @vitest-environment jsdom
import type { Page } from "@playwright/test";
import { expect, it, vi } from "vitest";
import { installReadiness } from "./readiness";

it("waits for startup timers, releases cancelled timers, and ignores periodic refreshes", async () => {
  vi.useFakeTimers();
  // Vitest installs Node-style handles even in jsdom. Browser timer handles
  // are numbers; expose that boundary while retaining the fake clock.
  const timers = new Map<number, ReturnType<typeof setTimeout>>();
  const schedule = globalThis.setTimeout.bind(globalThis);
  const cancel = globalThis.clearTimeout.bind(globalThis);
  let nextId = 0;
  const originalTimeout = window.setTimeout.bind(window);
  const originalClear = window.clearTimeout.bind(window);
  Reflect.set(
    window,
    "setTimeout",
    (handler: unknown, delay?: number, ...args: unknown[]) => {
      if (typeof handler !== "function") throw new Error("Expected a callback");
      const id = ++nextId;
      timers.set(
        id,
        schedule(() => {
          Reflect.apply(handler, window, args);
        }, delay),
      );
      return id;
    },
  );
  Reflect.set(window, "clearTimeout", (id: unknown) => {
    if (typeof id === "number") cancel(timers.get(id));
  });
  const page = {
    addInitScript: async (script: unknown) => {
      if (typeof script !== "function")
        throw new Error("Expected an init script");
      Reflect.apply(script, undefined, []);
      await Promise.resolve();
    },
  } as unknown as Page;
  try {
    await installReadiness(page);
    const callback = vi.fn();
    window.setTimeout(callback, 1000);
    expect(Reflect.get(window, "__visualPendingTimers")).toBe(1);
    await vi.advanceTimersByTimeAsync(999);
    expect(callback).not.toHaveBeenCalled();
    expect(Reflect.get(window, "__visualPendingTimers")).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(callback).toHaveBeenCalledTimes(1);
    expect(Reflect.get(window, "__visualPendingTimers")).toBe(0);

    const cancelled = window.setTimeout(callback, 500);
    window.clearTimeout(cancelled);
    window.setTimeout(callback, 60_000);
    const interval = window.setInterval(callback, 1000);
    expect(Reflect.get(window, "__visualPendingTimers")).toBe(0);
    await vi.advanceTimersByTimeAsync(500);
    expect(callback).toHaveBeenCalledTimes(1);
    window.clearInterval(interval);
  } finally {
    window.setTimeout = originalTimeout;
    window.clearTimeout = originalClear;
    vi.useRealTimers();
  }
});
