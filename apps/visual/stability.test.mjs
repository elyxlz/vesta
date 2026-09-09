import { expect, it, vi } from "vitest";
import { grabUntilStable } from "./stability.mjs";

it("does not accept briefly repeated frames before the stability window", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
  try {
    const grab = vi.fn(async () =>
      Buffer.from(Date.now() < 200 ? "loading" : "ready"),
    );
    const result = grabUntilStable(grab, {
      pollMs: 100,
      stableMs: 250,
      timeoutMs: 1000,
    });
    await vi.runAllTimersAsync();
    expect((await result).toString()).toBe("ready");
    expect(grab).toHaveBeenCalledTimes(6);
  } finally {
    vi.useRealTimers();
  }
});
