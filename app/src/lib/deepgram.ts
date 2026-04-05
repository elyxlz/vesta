import { DeepgramClient } from "@deepgram/sdk";

const DEEPGRAM_API_KEY = "3c8259a08a9b4b05f21079c1695ef169c7ff0faf";

const SAMPLE_RATE = 16000;

export interface DeepgramStreamOptions {
  onTranscript: (text: string) => void;
  onTurnEnd: (text: string) => void;
  onTurnStart: () => void;
  onError: (error: string) => void;
  eotThreshold?: number;
  eotTimeoutMs?: number;
}

export class DeepgramStream {
  private opts: DeepgramStreamOptions;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  private socket: any = null;
  private transcript = "";
  private active = false;

  constructor(opts: DeepgramStreamOptions) {
    this.opts = opts;
  }

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.transcript = "";

    if (!navigator.mediaDevices) {
      this.active = false;
      throw new Error("Microphone requires HTTPS — connect via the tunnel or localhost");
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      this.active = false;
      if (err instanceof DOMException) {
        if (err.name === "NotAllowedError") throw new Error("Microphone permission denied");
        if (err.name === "NotFoundError") throw new Error("No microphone found");
        if (err.name === "NotReadableError") throw new Error("Microphone is in use by another app");
      }
      throw new Error("Could not access microphone");
    }

    let socket;
    try {
      const client = new DeepgramClient({ apiKey: DEEPGRAM_API_KEY });
      socket = await client.listen.v2.connect({
        model: "flux-general-en",
        eot_threshold: this.opts.eotThreshold ?? 0.8,
        eot_timeout_ms: this.opts.eotTimeoutMs ?? 10000,
        encoding: "linear16",
        sample_rate: SAMPLE_RATE,
        Authorization: `Token ${DEEPGRAM_API_KEY}`,
      });
    } catch {
      this.cleanup();
      throw new Error("Could not connect to transcription service");
    }

    socket.on("message", (data) => {
      if (data.type === "TurnInfo") {
        if (data.event === "StartOfTurn") {
          this.transcript = "";
          this.opts.onTurnStart();
        }
        if (data.transcript) {
          this.transcript = data.transcript;
          this.opts.onTranscript(this.transcript);
        }
        if (data.event === "EndOfTurn") {
          const text = this.transcript.trim();
          if (text) this.opts.onTurnEnd(text);
          this.transcript = "";
          this.opts.onTranscript("");
        }
        return;
      }

      if (data.type === "ConfigureFailure") {
        this.opts.onError("Transcription configuration error");
        this.stop();
      }
      if (data.type === "Error") {
        this.opts.onError("Transcription service error");
        this.stop();
      }
    });

    socket.on("error", (err) => {
      this.opts.onError(err.message || "Connection to transcription service lost");
      this.stop();
    });

    socket.on("close", () => {
      if (this.active) {
        this.active = false;
        this.opts.onError("Transcription connection closed unexpectedly");
      }
    });

    try {
      socket.connect();
      await socket.waitForOpen();
    } catch {
      this.cleanup();
      throw new Error("Transcription service connection timed out");
    }

    this.socket = socket;

    try {
      this.audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    } catch {
      this.cleanup();
      throw new Error("Could not initialize audio — browser may not support AudioContext");
    }

    try {
      await this.audioCtx.audioWorklet.addModule(new URL("./pcm-worklet.js", import.meta.url).href);
    } catch {
      this.cleanup();
      throw new Error("Could not load audio worklet");
    }

    const source = this.audioCtx.createMediaStreamSource(this.stream);
    const workletNode = new AudioWorkletNode(this.audioCtx, "pcm-processor", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
    });

    workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
      if (!this.active || !this.socket) return;
      try {
        const pcm = floatTo16BitPCM(e.data);
        this.socket.sendMedia(pcm);
      } catch {
        // socket may have closed between check and send — ignore
      }
    };

    source.connect(workletNode);
    workletNode.connect(this.audioCtx.destination);
  }

  stop(): void {
    if (!this.active) return;
    this.active = false;

    const text = this.transcript.trim();
    if (text) {
      this.opts.onTurnEnd(text);
      this.transcript = "";
      this.opts.onTranscript("");
    }

    this.cleanup();
  }

  isActive(): boolean {
    return this.active;
  }

  private cleanup(): void {
    if (this.socket) {
      try { this.socket.close(); } catch { /* ignore */ }
      this.socket = null;
    }
    if (this.audioCtx) {
      try { this.audioCtx.close(); } catch { /* ignore */ }
      this.audioCtx = null;
    }
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
    this.active = false;
  }
}

function floatTo16BitPCM(float32: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}
