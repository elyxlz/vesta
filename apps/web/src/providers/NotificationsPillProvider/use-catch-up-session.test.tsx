import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCatchUpSession } from "./use-catch-up-session";

interface SessionInput {
  historyOpen: boolean;
  seenAt: number;
  lastAt: number | null;
}

function mount(initial: SessionInput) {
  const markSeen = vi.fn();
  const hook = renderHook(
    ({ historyOpen, seenAt, lastAt }: SessionInput) =>
      useCatchUpSession(historyOpen, seenAt, lastAt, markSeen),
    { initialProps: initial },
  );
  return { ...hook, markSeen };
}

describe("useCatchUpSession", () => {
  it("holds the watermark from open to close, immune to mid-session advances", () => {
    const session = mount({ historyOpen: true, seenAt: 100, lastAt: 200 });
    expect(session.result.current).toBe(100);
    // Another device catching up mid-session must not shift the split on screen.
    session.rerender({ historyOpen: true, seenAt: 300, lastAt: 350 });
    expect(session.result.current).toBe(100);
  });

  it("marks seen on close when something unseen was on offer, once", () => {
    const session = mount({ historyOpen: true, seenAt: 100, lastAt: 200 });
    session.rerender({ historyOpen: false, seenAt: 100, lastAt: 200 });
    expect(session.result.current).toBeNull();
    expect(session.markSeen).toHaveBeenCalledTimes(1);
  });

  it("does not mark seen when nothing arrived past the held watermark", () => {
    const session = mount({ historyOpen: true, seenAt: 200, lastAt: 200 });
    session.rerender({ historyOpen: false, seenAt: 200, lastAt: 200 });
    expect(session.markSeen).not.toHaveBeenCalled();
  });

  it("never marks seen while no session ever opened", () => {
    const session = mount({ historyOpen: false, seenAt: 0, lastAt: 500 });
    session.rerender({ historyOpen: false, seenAt: 0, lastAt: 600 });
    expect(session.result.current).toBeNull();
    expect(session.markSeen).not.toHaveBeenCalled();
  });

  it("counts a live arrival during the session as offered, so close marks it", () => {
    const session = mount({ historyOpen: true, seenAt: 100, lastAt: 100 });
    // A notification lands while the surface is open (it shows in the list).
    session.rerender({ historyOpen: true, seenAt: 100, lastAt: 150 });
    session.rerender({ historyOpen: false, seenAt: 100, lastAt: 150 });
    expect(session.markSeen).toHaveBeenCalledTimes(1);
  });
});
