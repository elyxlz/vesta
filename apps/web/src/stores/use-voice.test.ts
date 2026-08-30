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
import {
  CONVERSATION_INACTIVITY_MS,
  useVoice,
  type VoiceMode,
} from "@/stores/use-voice";
import { useToastStore } from "@/stores/use-toast";
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
  // Node has no Web Audio; tests that record stub it in.
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
      // The gate is decided synchronously before the queue's first await, so a
      // registration would already have fired here.
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

  it("stopSpeech mid-queue drops the unplayed rest and ends speaking", async () => {
    useVoice.getState()._setTtsStatus(ENABLED_TTS);
    // Hold the first registration open so "second" is still queued when we stop.
    let release: (value: { id: string }) => void = () => undefined;
    apiJsonMock.mockReturnValueOnce(
      new Promise<{ id: string }>((resolve) => {
        release = resolve;
      }),
    );

    useVoice.getState().speak("first");
    useVoice.getState().speak("second");
    expect(useVoice.getState().isSpeaking).toBe(true);

    useVoice.getState().stopSpeech();
    release({ id: "a" });
    await vi.waitFor(() => expect(useVoice.getState().isSpeaking).toBe(false));
    // Let the superseded loop run to completion before asserting nothing more played.
    await new Promise<void>((resolve) => setTimeout(resolve, 0));

    expect(apiJsonMock).toHaveBeenCalledTimes(1);
    expect(FakeAudio.created.map((a) => a.src)).not.toContain(
      expect.stringContaining("/stream/b"),
    );
    expect(useVoice.getState().isSpeaking).toBe(false);
  });
});

// A Web Audio stand-in that lets Transcriber.start() run to completion, so the
// recording-mode tests reach the socket message handler that routes transcripts.
class FakeAudioContext {
  audioWorklet = { addModule: () => Promise.resolve() };
  destination = {};
  createMediaStreamSource() {
    return { connect: () => undefined };
  }
  close(): Promise<void> {
    return Promise.resolve();
  }
}

class FakeWorkletNode {
  port = { onmessage: null };
  connect(): void {
    /* noop */
  }
}

class RecordingSocket extends FakeSocket {
  static instances: RecordingSocket[] = [];
  constructor(url: string) {
    super(url);
    RecordingSocket.instances.push(this);
  }
  emit(event: "StartOfTurn" | "Update" | "EndOfTurn", transcript: string) {
    this.onmessage?.({
      data: JSON.stringify({ type: "TurnInfo", event, transcript }),
    });
  }
}

const ENABLED_STT = { configured: true, provider: "deepgram", enabled: true };

async function startRecording(mode: VoiceMode) {
  useVoice.getState().startVoice(mode);
  await vi.waitFor(() => {
    expect(RecordingSocket.instances.length).toBeGreaterThan(0);
  });
  // start() finishes on the microtasks after the socket opens.
  await new Promise((resolve) => setTimeout(resolve, 0));
  const socket = RecordingSocket.instances.at(-1);
  if (!socket) throw new Error("no socket");
  return socket;
}

describe("recording modes", () => {
  let send: ReturnType<typeof vi.fn<(text: string) => void>>;
  let clearInput: ReturnType<typeof vi.fn<() => void>>;

  beforeEach(() => {
    useVoice.getState()._cleanup();
    RecordingSocket.instances = [];
    vi.stubGlobal("WebSocket", RecordingSocket);
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
    useVoice.getState()._setSttStatus(ENABLED_STT);
    send = vi.fn<(text: string) => void>();
    clearInput = vi.fn<() => void>();
    useVoice.getState().registerChat(send, clearInput);
  });

  it("dials the authed STT socket url on the ws scheme", async () => {
    const socket = await startRecording("dictation");
    expect(RecordingSocket.urls).toContain(
      "wss://host:8443/agents/test-agent/voice/stt/listen?token=tok",
    );
    useVoice.getState().stopVoice();
    expect(socket).toBeDefined();
  });

  it("marks the mode at press time, drops typed text, and clears on stop", async () => {
    useVoice.getState().startVoice("dictation");
    expect(useVoice.getState().recordingMode).toBe("dictation");
    expect(clearInput).toHaveBeenCalledTimes(1);
    await startRecording("dictation");
    useVoice.getState().stopVoice();
    expect(useVoice.getState().recordingMode).toBeNull();
  });

  it("dictation accumulates turns and sends them all on confirm", async () => {
    const socket = await startRecording("dictation");
    socket.emit("StartOfTurn", "");
    socket.emit("Update", "hello");
    socket.emit("EndOfTurn", "hello");
    expect(send).not.toHaveBeenCalled();
    socket.emit("StartOfTurn", "");
    socket.emit("Update", "there");
    expect(useVoice.getState().liveTranscript).toBe("hello there");
    useVoice.getState().stopVoice();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("hello there", "voice");
    expect(useVoice.getState().liveTranscript).toBe("");
  });

  it("a conversation sends each turn as it ends and keeps listening", async () => {
    const socket = await startRecording("conversation");
    socket.emit("StartOfTurn", "");
    socket.emit("Update", "first");
    socket.emit("EndOfTurn", "first");
    expect(send).toHaveBeenCalledWith("first", "voice");
    expect(useVoice.getState().recordingMode).toBe("conversation");
    socket.emit("StartOfTurn", "");
    socket.emit("EndOfTurn", "second");
    expect(send).toHaveBeenLastCalledWith("second", "voice");
    useVoice.getState().stopVoice();
    expect(send).toHaveBeenCalledTimes(2);
  });

  it("discarding a dictation sends nothing", async () => {
    const socket = await startRecording("dictation");
    socket.emit("StartOfTurn", "");
    socket.emit("EndOfTurn", "never mind");
    useVoice.getState().cancelVoice();
    expect(send).not.toHaveBeenCalled();
    expect(useVoice.getState().recordingMode).toBeNull();
    expect(useVoice.getState().liveTranscript).toBe("");
  });

  it("reports listening once the microphone and socket are up", async () => {
    useVoice.getState().startVoice("conversation");
    expect(useVoice.getState().listening).toBe(false);
    await startRecording("conversation");
    expect(useVoice.getState().listening).toBe(true);
    useVoice.getState().stopVoice();
    expect(useVoice.getState().listening).toBe(false);
  });

  it("a user turn always cuts playback in a conversation, whatever interrupt_tts says", async () => {
    useVoice.getState()._setSttStatus({
      ...ENABLED_STT,
      settings: [
        { key: "interrupt_tts", type: "bool", label: "", value: false },
      ],
    });
    useVoice.getState()._setTtsStatus(ENABLED_TTS);
    const socket = await startRecording("conversation");
    useVoice.getState().speak("a long reply");
    await vi.waitFor(() => {
      expect(useVoice.getState().isSpeaking).toBe(true);
    });
    socket.emit("StartOfTurn", "");
    expect(useVoice.getState().isSpeaking).toBe(false);
  });

  it("a conversation silent for the inactivity budget ends with a toast", async () => {
    const socket = await startRecording("conversation");
    vi.useFakeTimers();
    try {
      socket.emit("StartOfTurn", "");
      socket.emit("EndOfTurn", "last words");
      vi.advanceTimersByTime(CONVERSATION_INACTIVITY_MS - 1);
      expect(useVoice.getState().recordingMode).toBe("conversation");
      vi.advanceTimersByTime(1);
      expect(useVoice.getState().recordingMode).toBeNull();
      expect(useToastStore.getState().current?.title).toBe(
        "conversation ended after 15 minutes of silence",
      );
    } finally {
      vi.useRealTimers();
      useToastStore.getState().dismiss();
    }
  });

  it("a transcription error mid-conversation resets the session and disarms the inactivity toast", async () => {
    const socket = await startRecording("conversation");
    vi.useFakeTimers();
    try {
      socket.onmessage?.({ data: JSON.stringify({ type: "Error" }) });
      expect(useVoice.getState()).toMatchObject({
        recordingMode: null,
        listening: false,
        liveTranscript: "",
        voiceError: "Transcription service error",
      });
      vi.advanceTimersByTime(CONVERSATION_INACTIVITY_MS);
      expect(useToastStore.getState().current).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("a microphone failure of a session already ended never reports", async () => {
    let denyMicrophone: (reason: Error) => void = () => undefined;
    vi.stubGlobal("navigator", {
      mediaDevices: {
        getUserMedia: () =>
          new Promise((_resolve, reject) => {
            denyMicrophone = reject;
          }),
      },
    });
    useVoice.getState().startVoice("dictation");
    useVoice.getState().cancelVoice();
    denyMicrophone(new DOMException("denied", "NotAllowedError"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(useVoice.getState().voiceError).toBeNull();
  });

  it("a release before the microphone opens still ends the session", async () => {
    useVoice.getState().startVoice("dictation");
    useVoice.getState().stopVoice();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(useVoice.getState().recordingMode).toBeNull();
    expect(RecordingSocket.instances).toHaveLength(0);
  });
});
