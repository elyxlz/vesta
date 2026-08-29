import { describe, it, expect, beforeEach, vi } from "vitest";

// The true edges of the voice paths: the HTTP call that registers TTS text
// (POST /voice/tts/prepare), the authed-url owner that builds both the streamed
// GET url and the STT socket url, and the media primitives (<audio>, WebSocket)
// that carry them. The credential is the whole point — a media element and a
// WebSocket cannot send a header, so both urls carry the refreshed access token
// in the query string. Everything between the edges (the store's gate and queue,
// streamSpeech, and Transcriber) runs for real, because that is the layer that
// decides whether audio ever reaches the voice endpoint at all.
vi.mock("@/api/client", () => ({ apiJson: vi.fn() }));
vi.mock("@/lib/authed-url", () => ({
  authedUrl: vi.fn((path: string) =>
    Promise.resolve(`https://host:8443${path}?token=tok`),
  ),
  websocketUrl: vi.fn((path: string) =>
    Promise.resolve(`wss://host:8443${path}?token=tok`),
  ),
}));

import { apiJson } from "@/api/client";
import { useVoice } from "@/stores/use-voice";
import { Transcriber, type TtsStatus } from "@/lib/voice";

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
  pause(): void {
    /* noop */
  }
}

class FakeSocket {
  static urls: string[] = [];
  binaryType = "";
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { reason: string }) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  constructor(url: string) {
    FakeSocket.urls.push(url);
    queueMicrotask(() => this.onopen?.());
  }
  close(): void {
    /* noop */
  }
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
  FakeSocket.urls = [];
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () => Promise.resolve({ getTracks: () => [] }),
    },
  });
  // Node has no Web Audio, so the microphone pipeline is where start() gives up.
  // The socket url is already recorded by then, which is what the STT assertion
  // reads.
  vi.stubGlobal("AudioContext", function AudioContextStub(): never {
    throw new Error("no Web Audio in node");
  });
  apiJsonMock.mockReset();
  apiJsonMock.mockResolvedValue({ id: "tts-1" });
});

describe("speak() — the assistant-message TTS trigger", () => {
  it("registers the text and streams it from the voice endpoint when TTS is enabled", async () => {
    useVoice.getState()._setTtsStatus(ENABLED_TTS);

    useVoice.getState().speak("hello there");

    await vi.waitFor(() => expect(apiJsonMock).toHaveBeenCalledTimes(1));

    // The text was registered via POST /voice/tts/prepare ...
    const [path, init] = apiJsonMock.mock.calls[0] ?? [];
    expect(path).toBe("/agents/test-agent/voice/tts/prepare");
    expect(init).toMatchObject({ method: "POST" });
    const body = init?.body;
    if (typeof body !== "string") throw new Error("expected a string body");
    expect(JSON.parse(body)).toEqual({
      text: "hello there",
    });

    // ... and the returned id was played from the streamed GET url.
    await vi.waitFor(() => expect(FakeAudio.created).toHaveLength(1));
    expect(FakeAudio.created[0]?.src).toBe(
      "https://host:8443/agents/test-agent/voice/tts/stream/tts-1?token=tok",
    );
  });

  const gateCases: {
    name: string;
    setup: () => void;
    expectSpeechDisabled?: boolean;
  }[] = [
    {
      name: "TTS disabled",
      setup: () =>
        useVoice.getState()._setTtsStatus({ ...ENABLED_TTS, enabled: false }),
    },
    {
      // The backend omits `enabled` only when it is false, but a regression that
      // dropped the flag must not silently start (or stop) speaking.
      name: "status missing the enabled flag",
      setup: () =>
        useVoice
          .getState()
          ._setTtsStatus({ configured: true, provider: "elevenlabs" }),
      expectSpeechDisabled: true,
    },
    {
      name: "no agent selected",
      setup: () => {
        useVoice.getState()._setAgentContext(null, {}, undefined);
        useVoice.getState()._setTtsStatus(ENABLED_TTS);
      },
    },
  ];

  it.each(gateCases)(
    "makes no network call — the silent gate ($name)",
    async ({ setup, expectSpeechDisabled }) => {
      setup();

      useVoice.getState().speak("hello there");
      // Give any errant async queue work a chance to fire.
      await Promise.resolve();
      await Promise.resolve();

      expect(apiJsonMock).not.toHaveBeenCalled();
      expect(FakeAudio.created).toHaveLength(0);
      if (expectSpeechDisabled) {
        expect(useVoice.getState().speechEnabled).toBe(false);
      }
    },
  );

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

describe("STT socket url", () => {
  it("dials the authed URL on the ws scheme", async () => {
    await expect(
      new Transcriber({
        agentName: "my-agent",
        onTranscript: () => undefined,
        onTurnEnd: () => undefined,
        onTurnStart: () => undefined,
        onError: () => undefined,
      }).start(),
    ).rejects.toThrow(/Could not initialize audio/);

    expect(FakeSocket.urls).toEqual([
      "wss://host:8443/agents/my-agent/voice/stt/listen?token=tok",
    ]);
  });
});
