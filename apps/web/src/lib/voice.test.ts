import { describe, it, expect, beforeEach, vi } from "vitest";

// The credential is the whole point of these tests. A media element and a WebSocket cannot send
// a header, so both voice URLs carry the refreshed access token in the query string through the
// authed-url owner. That owner and the api client are the true edges; streamSpeech and
// Transcriber run for real.
vi.mock("@/api/client", () => ({ apiJson: vi.fn() }));
vi.mock("@/lib/authed-url", () => ({
  authedUrl: vi.fn((path: string) =>
    Promise.resolve(`https://host:8443${path}?token=access-token`),
  ),
  websocketUrl: vi.fn((path: string) =>
    Promise.resolve(`wss://host:8443${path}?token=access-token`),
  ),
}));

import { apiJson } from "@/api/client";
import { Transcriber, streamSpeech } from "@/lib/voice";

const apiJsonMock = vi.mocked(apiJson);

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
});

describe("TTS playback url", () => {
  it("streams through the authed query URL with encoded segments", async () => {
    apiJsonMock.mockResolvedValue({ id: "utterance 1" });

    await streamSpeech("hello there", "my agent");

    expect(FakeAudio.created[0]?.src).toBe(
      "https://host:8443/agents/my%20agent/voice/tts/stream/utterance%201?token=access-token",
    );
  });
});

describe("STT socket url", () => {
  it("dials the authed URL on the ws scheme", async () => {
    await expect(new Transcriber(TRANSCRIBER_OPTS).start()).rejects.toThrow(
      /Could not initialize audio/,
    );

    expect(FakeSocket.urls).toEqual([
      "wss://host:8443/agents/my-agent/voice/stt/listen?token=access-token",
    ]);
  });
});
