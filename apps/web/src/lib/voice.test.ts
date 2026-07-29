import { describe, it, expect, beforeEach, vi } from "vitest";

// The credential is the whole point of these tests. A media element and a WebSocket cannot send
// a header, so both voice URLs carry a token in the query string, and that token must be a minted
// voice service key rather than the gateway access token. The service-key cache, the connection,
// and the two carriers are the true edges; streamSpeech and Transcriber run for real.
vi.mock("@/api/client", () => ({ apiJson: vi.fn() }));
vi.mock("@/lib/connection", () => ({
  getConnection: vi.fn(() => ({
    url: "https://host:8443",
    accessToken: "access-token",
  })),
}));
vi.mock("@/lib/service-key-cache", () => ({
  serviceKeys: { get: vi.fn(() => Promise.resolve("voice-key-1")) },
}));

import { apiJson } from "@/api/client";
import { serviceKeys } from "@/lib/service-key-cache";
import { Transcriber, streamSpeech } from "@/lib/voice";

const apiJsonMock = vi.mocked(apiJson);
const serviceKeysMock = vi.mocked(serviceKeys);

// Stands in for the browser <audio> element, reporting playback finished on the next microtask so
// streamSpeech's await resolves without a real media stack (these tests run in node, not jsdom).
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

const TRANSCRIBER_OPTS = {
  agentName: "my-agent",
  onTranscript: () => undefined,
  onTurnEnd: () => undefined,
  onTurnStart: () => undefined,
  onError: () => undefined,
};

beforeEach(() => {
  FakeAudio.created = [];
  FakeSocket.urls = [];
  vi.stubGlobal("Audio", FakeAudio);
  vi.stubGlobal("WebSocket", FakeSocket);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () => Promise.resolve({ getTracks: () => [] }),
    },
  });
  // Node has no Web Audio, so the microphone pipeline is where start() gives up. The socket url is
  // already recorded by then, which is what the assertion below reads.
  vi.stubGlobal("AudioContext", function AudioContextStub(): never {
    throw new Error("no Web Audio in node");
  });
  apiJsonMock.mockReset();
  serviceKeysMock.get.mockClear();
});

describe("TTS playback url", () => {
  it("carries a minted voice service key, never the access token", async () => {
    apiJsonMock.mockResolvedValue({ id: "utterance 1" });

    await streamSpeech("hello there", "my agent");

    expect(serviceKeysMock.get).toHaveBeenCalledWith("my agent", "voice");
    expect(FakeAudio.created[0]?.src).toBe(
      "https://host:8443/agents/my%20agent/voice/tts/stream/utterance%201?token=voice-key-1",
    );
  });
});

describe("STT socket url", () => {
  it("carries a minted voice service key on the ws scheme", async () => {
    await expect(new Transcriber(TRANSCRIBER_OPTS).start()).rejects.toThrow(
      /Could not initialize audio/,
    );

    expect(serviceKeysMock.get).toHaveBeenCalledWith("my-agent", "voice");
    expect(FakeSocket.urls).toEqual([
      "wss://host:8443/agents/my-agent/voice/stt/listen?token=voice-key-1",
    ]);
  });
});
