import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("@/api/client", () => ({ apiJson: vi.fn() }));
vi.mock("@/lib/authed-url", () => ({
  authedUrl: vi.fn((path: string) => Promise.resolve(`https://h${path}`)),
  websocketUrl: vi.fn((path: string) => Promise.resolve(`wss://h${path}`)),
}));

import { MAX_PENDING_AUDIO_BYTES, Transcriber } from "@/lib/voice";

// A socket that opens only when the test says so, holding start() at the dial.
class HeldSocket {
  static current: HeldSocket | null = null;
  sent: ArrayBuffer[] = [];
  binaryType = "";
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((event: { reason: string }) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  constructor() {
    HeldSocket.current = this;
  }
  send(data: ArrayBuffer): void {
    this.sent.push(data);
  }
  close(): void {
    /* noop */
  }
}

class FakeWorkletNode {
  static current: FakeWorkletNode | null = null;
  port: { onmessage: ((e: { data: Float32Array }) => void) | null } = {
    onmessage: null,
  };
  constructor() {
    FakeWorkletNode.current = this;
  }
  connect(): void {
    /* noop */
  }
}

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

function transcriber(): Transcriber {
  return new Transcriber({
    agentName: "a",
    onTranscript: () => undefined,
    onTurnEnd: () => undefined,
    onTurnStart: () => undefined,
    onError: () => undefined,
  });
}

function speak(samples: number): void {
  FakeWorkletNode.current?.port.onmessage?.({
    data: new Float32Array(samples),
  });
}

beforeEach(() => {
  HeldSocket.current = null;
  FakeWorkletNode.current = null;
  vi.stubGlobal("WebSocket", HeldSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: () => Promise.resolve({ getTracks: () => [] }),
    },
  });
});

describe("Transcriber audio captured before the socket opens", () => {
  it("is flushed to the socket the moment it opens, in order", async () => {
    const stt = transcriber();
    const started = stt.start();
    await vi.waitFor(() => {
      expect(HeldSocket.current).not.toBeNull();
    });
    speak(10);
    speak(20);
    HeldSocket.current?.onopen?.();
    await started;
    const sent = HeldSocket.current?.sent ?? [];
    expect(sent.map((f) => f.byteLength)).toEqual([20, 40]);
    speak(5);
    expect(sent).toHaveLength(3);
  });

  it("keeps only the newest frames up to the pending cap", async () => {
    const stt = transcriber();
    const started = stt.start();
    await vi.waitFor(() => {
      expect(HeldSocket.current).not.toBeNull();
    });
    const frame = MAX_PENDING_AUDIO_BYTES / 2 / 2;
    speak(frame);
    speak(frame);
    speak(1);
    HeldSocket.current?.onopen?.();
    await started;
    const sent = HeldSocket.current?.sent ?? [];
    expect(sent.map((f) => f.byteLength)).toEqual([
      MAX_PENDING_AUDIO_BYTES / 2,
      2,
    ]);
  });
});

describe("Transcriber.stop()", () => {
  it("drops an in-flight partial instead of reporting it as a turn", async () => {
    const onTurnEnd = vi.fn();
    const stt = new Transcriber({
      agentName: "a",
      onTranscript: () => undefined,
      onTurnEnd,
      onTurnStart: () => undefined,
      onError: () => undefined,
    });
    const started = stt.start();
    await vi.waitFor(() => {
      expect(HeldSocket.current).not.toBeNull();
    });
    HeldSocket.current?.onopen?.();
    await started;
    HeldSocket.current?.onmessage?.({
      data: JSON.stringify({
        type: "TurnInfo",
        event: "Update",
        transcript: "half a",
      }),
    });
    stt.stop();
    expect(onTurnEnd).not.toHaveBeenCalled();
  });
});
