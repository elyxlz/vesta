import { describe, it, expect, beforeEach, vi } from "vitest";

// The true edges of the TTS playback path: the HTTP call that registers the
// text (POST /voice/tts/prepare), the connection used to build the streamed
// GET url, and the <audio> element that plays it. Everything between them —
// the store's gate, queue, and streamSpeech — runs for real, because that is
// the layer that decides whether an assistant message ever reaches the voice
// endpoint at all.
vi.mock("@/api/client", () => ({ apiJson: vi.fn() }));
vi.mock("@/lib/connection", () => ({
  getConnection: vi.fn(() => ({
    url: "https://host:8443",
    accessToken: "tok",
  })),
}));

import { apiJson } from "@/api/client";
import { useVoice } from "@/stores/use-voice";
import type { TtsStatus } from "@/lib/voice";

const apiJsonMock = vi.mocked(apiJson);

// A stand-in for the browser <audio> element that reports playback finished on
// the next microtask, so streamSpeech's await resolves without a real media
// stack (the test runs in node, not jsdom).
class FakeAudio {
  static created: FakeAudio[] = [];
  src: string;
  preload = "";
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(src?: string) {
    this.src = src ?? "";
    FakeAudio.created.push(this);
  }
  play(): Promise<void> {
    queueMicrotask(() => this.onended?.());
    return Promise.resolve();
  }
  pause(): void {}
}

const ENABLED_TTS: TtsStatus = {
  configured: true,
  provider: "elevenlabs",
  enabled: true,
};

beforeEach(() => {
  // The store is a module singleton with playback state living in module-level
  // refs; stopSpeech() drains them so each test starts clean.
  useVoice.getState().stopSpeech();
  useVoice.getState()._setAgentContext("test-agent", {}, undefined);
  useVoice.getState()._setSttStatus(null);
  useVoice.getState()._setTtsStatus(null);
  FakeAudio.created = [];
  vi.stubGlobal("Audio", FakeAudio);
  apiJsonMock.mockReset();
  apiJsonMock.mockResolvedValue({ id: "tts-1" });
});

describe("speak() — the assistant-message TTS trigger", () => {
  it("registers the text and streams it from the voice endpoint when TTS is enabled", async () => {
    useVoice.getState()._setTtsStatus(ENABLED_TTS);

    useVoice.getState().speak("hello there");

    await vi.waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));

    // The text was registered via POST /voice/tts/prepare ...
    const [path, init] = apiJsonMock.mock.calls[0];
    expect(path).toBe("/agents/test-agent/voice/tts/prepare");
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      text: "hello there",
    });

    // ... and the returned id was played from the streamed GET url.
    await vi.waitFor(() => expect(FakeAudio.created).toHaveLength(1));
    expect(FakeAudio.created[0].src).toBe(
      "https://host:8443/agents/test-agent/voice/tts/stream/tts-1?token=tok",
    );
  });

  it("makes no network call when TTS is disabled — the silent gate", async () => {
    useVoice.getState()._setTtsStatus({ ...ENABLED_TTS, enabled: false });

    useVoice.getState().speak("hello there");
    // Give any errant async queue work a chance to fire.
    await Promise.resolve();
    await Promise.resolve();

    expect(apiJsonMock).not.toHaveBeenCalled();
    expect(FakeAudio.created).toHaveLength(0);
  });

  it("treats a status missing the enabled flag as disabled", async () => {
    // The backend omits `enabled` only when it is false, but a regression that
    // dropped the flag must not silently start (or stop) speaking.
    useVoice
      .getState()
      ._setTtsStatus({ configured: true, provider: "elevenlabs" });

    useVoice.getState().speak("hello there");
    await Promise.resolve();
    await Promise.resolve();

    expect(useVoice.getState().speechEnabled).toBe(false);
    expect(apiJsonMock).not.toHaveBeenCalled();
  });

  it("makes no network call before an agent is selected", async () => {
    useVoice.getState()._setAgentContext(null, {}, undefined);
    useVoice.getState()._setTtsStatus(ENABLED_TTS);

    useVoice.getState().speak("hello there");
    await Promise.resolve();
    await Promise.resolve();

    expect(apiJsonMock).not.toHaveBeenCalled();
  });

  it("streams every queued message in order", async () => {
    useVoice.getState()._setTtsStatus(ENABLED_TTS);
    apiJsonMock.mockResolvedValueOnce({ id: "a" });
    apiJsonMock.mockResolvedValueOnce({ id: "b" });

    useVoice.getState().speak("first");
    useVoice.getState().speak("second");

    await vi.waitFor(() => expect(FakeAudio.created).toHaveLength(2));
    expect(FakeAudio.created.map((a) => a.src)).toEqual([
      "https://host:8443/agents/test-agent/voice/tts/stream/a?token=tok",
      "https://host:8443/agents/test-agent/voice/tts/stream/b?token=tok",
    ]);
  });
});
