import { describe, expect, it } from "vitest";
import { voiceTargetName } from "./voice-target";

describe("voiceTargetName", () => {
  it("names the agent whose voice services a direct room uses", () => {
    expect(voiceTargetName("aria")).toBe("aria");
  });

  // A group room passes no agent, so the TTS status read stays home instead of asking the node
  // for `/agents//voice/tts/status`.
  it("has no target for a room with no single agent", () => {
    expect(voiceTargetName("")).toBeNull();
  });
});
