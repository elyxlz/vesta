import { describe, expect, it } from "vitest";
import { orbVisual } from "./orb";

describe("orb visual", () => {
  it("dims only while a conversation waits for the wake phrase", () => {
    expect(orbVisual("alive").opacity).toBe(1);
    expect(orbVisual("alive", "listening").opacity).toBe(1);
    expect(orbVisual("alive", "talking").opacity).toBe(1);
    expect(orbVisual("alive", "waiting").opacity).toBeLessThan(1);
  });

  it("breathes slower while it waits than while it listens", () => {
    const waiting = orbVisual("alive", "waiting");
    const listening = orbVisual("alive", "listening");
    expect(waiting.breathes).toBe(true);
    expect(waiting.pulseHalfMs).toBeGreaterThan(listening.pulseHalfMs);
    expect(waiting.pulseScale).toBeLessThan(listening.pulseScale);
  });
});
