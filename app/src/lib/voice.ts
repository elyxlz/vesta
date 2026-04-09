import { apiFetch, apiJson } from "@/api/client";
import { getConnection } from "@/lib/connection";

const SAMPLE_RATE = 16000;

function voicePost(
  agentName: string,
  path: string,
  body: unknown,
): Promise<unknown> {
  return apiJson(`/agents/${encodeURIComponent(agentName)}/voice/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Dynamic settings ---

export interface SettingDef {
  key: string;
  type: "bool" | "number" | "select";
  label: string;
  description?: string;
  value: unknown;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  unit?: string;
  options?: Array<{
    value: string;
    label: string;
    preview?: string;
    custom?: boolean;
    [k: string]: unknown;
  }>;
}

export const setVoiceSetting = (
  n: string,
  domain: "stt" | "tts",
  key: string,
  value: unknown,
) => voicePost(n, `${domain}/set`, { key, value });

// --- STT ---

export interface SttStatus {
  configured: boolean;
  provider: string | null;
  enabled?: boolean;
  settings?: SettingDef[];
}

export async function fetchSttStatus(
  agentName: string,
  signal?: AbortSignal,
): Promise<SttStatus> {
  return apiJson<SttStatus>(
    `/agents/${encodeURIComponent(agentName)}/voice/stt/status`,
    { signal },
  );
}

export interface SttUsage {
  usage?: { results?: { hours?: number }[] };
  balance?: { balances?: { amount?: number; units?: string }[] };
}

export async function fetchSttUsage(agentName: string): Promise<SttUsage> {
  return apiJson<SttUsage>(
    `/agents/${encodeURIComponent(agentName)}/voice/stt/usage`,
  );
}

export const setSttEnabled = (n: string, value: boolean) =>
  voicePost(n, "stt/set-enabled", { value });
export const setSttAutoSend = (n: string, value: boolean) =>
  voicePost(n, "stt/set-auto-send", { value });
export const setSttEot = (
  n: string,
  params: { threshold?: number; timeout_ms?: number },
) => voicePost(n, "stt/set-eot", params);

// --- TTS ---

export interface TtsStatus {
  configured: boolean;
  provider: string | null;
  enabled?: boolean;
  settings?: SettingDef[];
}

export async function fetchTtsStatus(
  agentName: string,
  signal?: AbortSignal,
): Promise<TtsStatus> {
  return apiJson<TtsStatus>(
    `/agents/${encodeURIComponent(agentName)}/voice/tts/status`,
    { signal },
  );
}

export interface TtsUsage {
  usage?: { character_count?: number; character_limit?: number };
}

export async function fetchTtsUsage(agentName: string): Promise<TtsUsage> {
  return apiJson<TtsUsage>(
    `/agents/${encodeURIComponent(agentName)}/voice/tts/usage`,
  );
}

export const setTtsEnabled = (n: string, value: boolean) =>
  voicePost(n, "tts/set-enabled", { value });
export const setTtsVoice = (n: string, voiceId: string) =>
  voicePost(n, "tts/set-voice", { voice_id: voiceId });

// --- TTS playback ---

export async function streamSpeech(
  text: string,
  agentName: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await apiFetch(
    `/agents/${encodeURIComponent(agentName)}/voice/tts/speak`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal,
    },
  );

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("audio/mpeg") || contentType.includes("audio/mp3")) {
    return playStreamedAudio(res.body!, signal);
  }

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const audio = new Audio(url);
  if (signal) {
    signal.addEventListener("abort", () => {
      audio.pause();
      URL.revokeObjectURL(url);
    });
  }
  await new Promise<void>((resolve, reject) => {
    audio.onended = () => {
      URL.revokeObjectURL(url);
      resolve();
    };
    audio.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("Audio playback failed"));
    };
    audio.play().catch(reject);
  });
}

async function playStreamedAudio(
  body: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): Promise<void> {
  const mediaSource = new MediaSource();
  const audio = new Audio();
  audio.src = URL.createObjectURL(mediaSource);

  if (signal) {
    signal.addEventListener("abort", () => {
      audio.pause();
      URL.revokeObjectURL(audio.src);
    });
  }

  await new Promise<void>((resolve, reject) => {
    mediaSource.addEventListener(
      "sourceopen",
      async () => {
        let sourceBuffer: SourceBuffer;
        try {
          sourceBuffer = mediaSource.addSourceBuffer("audio/mpeg");
        } catch {
          URL.revokeObjectURL(audio.src);
          const reader = body.getReader();
          const chunks: Uint8Array[] = [];
          // eslint-disable-next-line no-constant-condition
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            chunks.push(value);
          }
          const blob = new Blob(chunks as BlobPart[], { type: "audio/mpeg" });
          audio.src = URL.createObjectURL(blob);
          audio.onended = () => {
            URL.revokeObjectURL(audio.src);
            resolve();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(audio.src);
            reject(new Error("Playback failed"));
          };
          audio.play().catch(reject);
          return;
        }

        const reader = body.getReader();
        const queue: Uint8Array[] = [];
        let ended = false;

        const appendNext = () => {
          if (sourceBuffer.updating) return;
          if (queue.length === 0) {
            if (ended && mediaSource.readyState === "open")
              mediaSource.endOfStream();
            return;
          }
          sourceBuffer.appendBuffer(queue.shift()!.buffer as ArrayBuffer);
        };

        sourceBuffer.addEventListener("updateend", appendNext);

        audio.onended = () => {
          URL.revokeObjectURL(audio.src);
          resolve();
        };
        audio.onerror = () => {
          URL.revokeObjectURL(audio.src);
          reject(new Error("Playback failed"));
        };
        audio.play().catch(reject);

        // eslint-disable-next-line no-constant-condition
        while (true) {
          const { done, value } = await reader.read();
          if (signal?.aborted) break;
          if (done) {
            ended = true;
            appendNext();
            break;
          }
          queue.push(value);
          appendNext();
        }
      },
      { once: true },
    );
  });
}

// --- STT streaming ---

export interface TranscriberOptions {
  agentName: string;
  onTranscript: (text: string) => void;
  onTurnEnd: (text: string) => void;
  onTurnStart: () => void;
  onError: (error: string) => void;
}

interface DeepgramEvent {
  type: string;
  event?: string;
  transcript?: string;
}

export class Transcriber {
  private opts: TranscriberOptions;
  private stream: MediaStream | null = null;
  private audioCtx: AudioContext | null = null;
  private socket: WebSocket | null = null;
  private transcript = "";
  private active = false;

  constructor(opts: TranscriberOptions) {
    this.opts = opts;
  }

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.transcript = "";

    if (!navigator.mediaDevices) {
      this.active = false;
      throw new Error(
        "Microphone requires HTTPS — connect via the tunnel or localhost",
      );
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
        if (err.name === "NotAllowedError")
          throw new Error("Microphone permission denied");
        if (err.name === "NotFoundError")
          throw new Error("No microphone found");
        if (err.name === "NotReadableError")
          throw new Error("Microphone is in use by another app");
      }
      throw new Error("Could not access microphone");
    }

    let socket: WebSocket;
    try {
      const url = this.buildWsUrl();
      socket = new WebSocket(url);
      socket.binaryType = "arraybuffer";
      await new Promise<void>((resolve, reject) => {
        socket.onopen = () => resolve();
        socket.onerror = () => reject(new Error("websocket error"));
        socket.onclose = (ev) =>
          reject(new Error(ev.reason || "closed before open"));
      });
    } catch {
      this.cleanup();
      throw new Error("Could not connect to transcription service");
    }

    socket.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      let data: DeepgramEvent;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
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
    };

    socket.onerror = () => {
      this.opts.onError("Connection to transcription service lost");
      this.stop();
    };

    socket.onclose = () => {
      if (this.active) {
        this.active = false;
        this.opts.onError("Transcription connection closed unexpectedly");
      }
    };

    this.socket = socket;

    try {
      this.audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    } catch {
      this.cleanup();
      throw new Error(
        "Could not initialize audio — browser may not support AudioContext",
      );
    }

    try {
      await this.audioCtx.audioWorklet.addModule(
        new URL("./pcm-worklet.js", import.meta.url).href,
      );
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
      if (
        !this.active ||
        !this.socket ||
        this.socket.readyState !== WebSocket.OPEN
      )
        return;
      try {
        const pcm = floatTo16BitPCM(e.data);
        this.socket.send(pcm);
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

  private buildWsUrl(): string {
    const conn = getConnection();
    if (!conn) throw new Error("not connected to vestad");
    const base = conn.url.replace(/^http/, "ws");
    const params = new URLSearchParams({ token: conn.accessToken });
    return `${base}/agents/${encodeURIComponent(this.opts.agentName)}/voice/stt/listen?${params.toString()}`;
  }

  private cleanup(): void {
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        /* ignore */
      }
      this.socket = null;
    }
    if (this.audioCtx) {
      try {
        this.audioCtx.close();
      } catch {
        /* ignore */
      }
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
