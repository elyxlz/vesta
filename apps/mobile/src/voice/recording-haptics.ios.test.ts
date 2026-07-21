import { describe, expect, it, vi } from "vitest";
import {
  setRecordingHapticsEnabled,
  triggerTranscriptHaptic,
} from "./recording-haptics.ios";

vi.mock("expo", () => ({
  requireOptionalNativeModule: vi.fn(() => null),
}));

describe("recording haptics without the native module", () => {
  it("keeps voice controls usable in an older development client", async () => {
    await expect(setRecordingHapticsEnabled(true)).resolves.toBeUndefined();
    await expect(triggerTranscriptHaptic()).resolves.toBeUndefined();
  });
});
