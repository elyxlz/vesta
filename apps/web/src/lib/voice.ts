import {
  serviceKeyQueryUrl,
  serviceKeySocketUrl,
  type AudioCapture,
  type VoiceDomainStatus,
  type VoiceSocketLike,
} from "@vesta/core";
import { apiJson } from "@/api/client";
import { getConnection } from "@/lib/connection";
import { serviceKeys } from "@/lib/service-key-cache";

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

// --- Status + dynamic settings (wire shapes owned by @vesta/core) ---

export type {
  VoiceSettingDef as SettingDef,
  VoiceDomainStatus as SttStatus,
  VoiceDomainStatus as TtsStatus,
} from "@vesta/core";

export const setVoiceSetting = (
  n: string,
  domain: "stt" | "tts",
  key: string,
  value: unknown,
): Promise<VoiceDomainStatus> =>
  voicePost(n, `${domain}/set`, { key, value }) as Promise<VoiceDomainStatus>;

// --- STT ---

export async function fetchSttStatus(
  agentName: string,
  signal?: AbortSignal,
): Promise<VoiceDomainStatus> {
  return apiJson<VoiceDomainStatus>(
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

// --- TTS ---

export async function fetchTtsStatus(
  agentName: string,
  signal?: AbortSignal,
): Promise<VoiceDomainStatus> {
  return apiJson<VoiceDomainStatus>(
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

// TTS playback runs through a native <audio> element pointed at a streamed GET,
// not JS-fetched bytes fed to MediaSource: the native media stack streams from
// the first byte on every webview (Android's System WebView has no reliable
// MSE for raw audio/mpeg) and owns audio routing including Bluetooth A2DP
// cold-start (issue #466). A media-element request can't carry an Authorization
// header and uses GET (no body), so the text is first registered via POST
// /tts/prepare; the element then streams GET /tts/stream/{id}?token=...

export function prepareSpeech(
  text: string,
  agentName: string,
  signal?: AbortSignal,
): Promise<string> {
  return apiJson<{ id: string }>(
    `/agents/${encodeURIComponent(agentName)}/voice/tts/prepare`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      signal,
    },
  ).then((res) => res.id);
}

async function ttsStreamUrl(agentName: string, id: string): Promise<string> {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const key = await serviceKeys.get(agentName, "voice");
  return serviceKeyQueryUrl(
    conn.url,
    agentName,
    "voice",
    key,
    `/tts/stream/${encodeURIComponent(id)}`,
  );
}

export async function streamPreparedSpeech(
  id: string,
  agentName: string,
  signal: AbortSignal,
): Promise<void> {
  const src = await ttsStreamUrl(agentName, id);
  if (signal.aborted) return;

  const audio = new Audio(src);
  audio.preload = "auto";

  await new Promise<void>((resolve, reject) => {
    const cleanup = () => {
      audio.onended = null;
      audio.onerror = null;
    };
    // Resolve (not reject) on abort so the caller's await completes instead
    // of hanging when playback is cancelled mid-stream.
    signal.addEventListener("abort", () => {
      cleanup();
      audio.pause();
      audio.src = "";
      resolve();
    });
    audio.onended = () => {
      cleanup();
      resolve();
    };
    audio.onerror = () => {
      cleanup();
      reject(new Error("Audio playback failed"));
    };
    audio.play().catch(reject);
  });
}

// --- Audio preload ---

const WORKLET_URL = new URL("./pcm-worklet.js", import.meta.url).href;
let preloadPromise: Promise<void> | null = null;

/**
 * Compile the PCM worklet module ahead of time via a throwaway AudioContext.
 * Browsers cache compiled worklet modules by URL, so subsequent
 * AudioContext.addModule calls resolve near-instantly.
 */
export function preloadAudio(): Promise<void> {
  if (preloadPromise) return preloadPromise;
  preloadPromise = (async () => {
    try {
      const ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      await ctx.audioWorklet.addModule(WORKLET_URL);
      await ctx.close();
    } catch {
      preloadPromise = null;
    }
  })();
  return preloadPromise;
}

// --- STT transport (the ports @vesta/core's voice session drives) ---

export async function buildListenUrl(agentName: string): Promise<string> {
  const conn = getConnection();
  if (!conn) throw new Error("not connected to vestad");
  const key = await serviceKeys.get(agentName, "voice");
  return serviceKeySocketUrl(conn.url, agentName, "voice", key, "/stt/listen");
}

export function createVoiceSocket(url: string): VoiceSocketLike {
  const socket = new WebSocket(url);
  socket.binaryType = "arraybuffer";
  const like: VoiceSocketLike = {
    send: (data) => {
      try {
        socket.send(data);
      } catch {
        // socket may have closed between check and send — ignore
      }
    },
    close: () => socket.close(),
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  socket.onopen = () => like.onopen?.();
  socket.onmessage = (ev) => {
    if (typeof ev.data === "string") like.onmessage?.(ev.data);
  };
  socket.onclose = (ev) => like.onclose?.(ev.reason);
  return like;
}

export function createMicCapture(): AudioCapture {
  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;

  const stop = (): void => {
    if (audioCtx) {
      audioCtx.close().catch(() => {
        /* already closed */
      });
      audioCtx = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
  };

  const start = async (onFrame: (pcm: ArrayBuffer) => void): Promise<void> => {
    if (!("mediaDevices" in navigator)) {
      throw new Error("Microphone requires a secure connection");
    }

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch (err) {
      if (err instanceof DOMException) {
        if (err.name === "NotAllowedError")
          throw new Error("Microphone permission denied", { cause: err });
        if (err.name === "NotFoundError")
          throw new Error("No microphone found", { cause: err });
        if (err.name === "NotReadableError")
          throw new Error("Microphone is in use by another app", {
            cause: err,
          });
      }
      throw new Error("Could not access microphone", { cause: err });
    }

    try {
      audioCtx = new AudioContext({ sampleRate: SAMPLE_RATE });
    } catch {
      stop();
      throw new Error(
        "Could not initialize audio — browser may not support AudioContext",
      );
    }

    try {
      await audioCtx.audioWorklet.addModule(WORKLET_URL);
    } catch {
      stop();
      throw new Error("Could not load audio worklet");
    }

    const source = audioCtx.createMediaStreamSource(stream);
    const workletNode = new AudioWorkletNode(audioCtx, "pcm-processor", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      channelCount: 1,
    });

    workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
      onFrame(floatTo16BitPCM(e.data));
    };

    source.connect(workletNode);
    workletNode.connect(audioCtx.destination);
  };

  return { start, stop };
}

function floatTo16BitPCM(float32: Float32Array): ArrayBuffer {
  const buf = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buf);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i] ?? 0));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buf;
}
