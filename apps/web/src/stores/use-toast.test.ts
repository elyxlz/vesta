import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useToastStore } from "./use-toast";

beforeEach(() => {
  vi.useFakeTimers();
  useToastStore.setState({ current: null });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useToastStore", () => {
  it("auto-dismisses a toast after its lifetime", () => {
    useToastStore.getState().show("info", "saved");
    expect(useToastStore.getState().current?.title).toBe("saved");
    vi.runAllTimers();
    expect(useToastStore.getState().current).toBeNull();
  });

  it("a superseded toast's timer does not dismiss its replacement", () => {
    useToastStore.getState().show("info", "first");
    vi.advanceTimersByTime(3000);
    useToastStore.getState().show("error", "second");
    // The first toast's timer fires now; the second is still within its lifetime.
    vi.advanceTimersByTime(1000);
    expect(useToastStore.getState().current?.title).toBe("second");
    vi.runAllTimers();
    expect(useToastStore.getState().current).toBeNull();
  });
});
