import { describe, expect, it, vi } from "vitest";
import {
  setRecordingHapticsEnabled,
  triggerTranscriptHaptic,
} from "./recording-haptics.android";

const { impactAsync } = vi.hoisted(() => ({
  impactAsync: vi.fn(async () => undefined),
}));

vi.mock("expo-haptics", () => ({
  impactAsync,
  ImpactFeedbackStyle: { Soft: "soft" },
}));

describe("recording haptics on Android", () => {
  it("keeps the iOS-only recording toggle a no-op", async () => {
    await expect(setRecordingHapticsEnabled(true)).resolves.toBeUndefined();
    expect(impactAsync).not.toHaveBeenCalled();
  });

  it("pulses a soft impact per transcript growth", async () => {
    await expect(triggerTranscriptHaptic()).resolves.toBeUndefined();
    expect(impactAsync).toHaveBeenCalledWith("soft");
  });
});
