import { describe, expect, it } from "vitest";
import type { SettingDef } from "../api/voice";
import {
  conversationMotion,
  conversationPhase,
  conversationPhaseLabel,
  conversationStage,
  splitSpokenTail,
  wakeWordBehavior,
} from "./conversation-panel";

describe("conversation stage", () => {
  it.each([
    { recordingMode: null, listening: false, expected: null },
    { recordingMode: "dictation", listening: true, expected: null },
    { recordingMode: "conversation", listening: false, expected: "starting" },
    { recordingMode: "conversation", listening: true, expected: "live" },
  ] as const)(
    "$recordingMode listening=$listening is $expected",
    ({ recordingMode, listening, expected }) => {
      expect(conversationStage({ recordingMode, listening })).toBe(expected);
    },
  );
});

describe("conversation phase", () => {
  const live = {
    listening: true,
    micMuted: false,
    speaking: false,
    thinking: false,
    wakeWaiting: false,
  };

  it("reads connecting until the session listens, whatever else is true", () => {
    expect(
      conversationPhase({ ...live, listening: false, speaking: true }),
    ).toBe("connecting");
  });

  it("ranks the agent talking above a muted mic, and mute above thinking", () => {
    expect(conversationPhase({ ...live, speaking: true, micMuted: true })).toBe(
      "speaking",
    );
    expect(conversationPhase({ ...live, micMuted: true, thinking: true })).toBe(
      "muted",
    );
    expect(conversationPhase({ ...live, thinking: true })).toBe("thinking");
    expect(conversationPhase(live)).toBe("listening");
  });

  it("waits for the wake phrase below thinking and above listening", () => {
    expect(
      conversationPhase({ ...live, wakeWaiting: true, thinking: true }),
    ).toBe("thinking");
    expect(conversationPhase({ ...live, wakeWaiting: true })).toBe("waiting");
  });
});

describe("conversation phase label", () => {
  it.each([
    { phase: "connecting", phrase: "hey aria", expected: "connecting…" },
    { phase: "waiting", phrase: "hey aria", expected: "say “hey aria”" },
    { phase: "waiting", phrase: null, expected: "waiting for the wake word" },
    { phase: "listening", phrase: "hey aria", expected: "listening" },
  ] as const)("$phase with $phrase", ({ phase, phrase, expected }) => {
    expect(conversationPhaseLabel(phase, phrase)).toBe(expected);
  });
});

describe("conversation motion", () => {
  const live = {
    listening: true,
    micMuted: false,
    speaking: false,
    wakeWaiting: false,
  };

  it.each([
    {
      name: "dialing",
      input: { ...live, listening: false },
      expected: undefined,
    },
    { name: "muted", input: { ...live, micMuted: true }, expected: undefined },
    {
      name: "a reply",
      input: { ...live, speaking: true, wakeWaiting: true },
      expected: "talking",
    },
    {
      name: "the wake gate",
      input: { ...live, wakeWaiting: true },
      expected: "waiting",
    },
    { name: "the user's floor", input: live, expected: "listening" },
  ] as const)("for $name is $expected", ({ input, expected }) => {
    expect(conversationMotion(input)).toBe(expected);
  });
});

describe("wake word behavior", () => {
  const setting = (key: string, value: unknown): SettingDef => ({
    key,
    type: "bool",
    label: key,
    value,
  });

  it("is null for a voice service with no wake word", () => {
    expect(wakeWordBehavior(undefined)).toBeNull();
    expect(wakeWordBehavior([setting("barge_in", true)])).toBeNull();
  });

  it("reads the switch and the phrase of this client", () => {
    expect(
      wakeWordBehavior([
        setting("wake_word", true),
        setting("wake_word_phrase", "hey vesta"),
      ]),
    ).toEqual({ on: true, phrase: "hey vesta" });
    expect(wakeWordBehavior([setting("wake_word", false)])).toEqual({
      on: false,
      phrase: null,
    });
  });
});

describe("spoken tail", () => {
  it("splits the last word off for emphasis", () => {
    expect(splitSpokenTail("book the room")).toEqual({
      head: "book the ",
      tail: "room",
    });
  });

  it("treats a single word as the tail", () => {
    expect(splitSpokenTail("hello")).toEqual({ head: "", tail: "hello" });
    expect(splitSpokenTail("")).toEqual({ head: "", tail: "" });
  });
});
