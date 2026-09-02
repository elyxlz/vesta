import { apiJson } from "@/api/client";
import { authedUrl, websocketUrl } from "@/lib/authed-url";

const SAMPLE_RATE = 16000;

function voicePost<T = unknown>(
  agentName: string,
  path: string,
  body: unknown,
): Promise<T> {
  return apiJson<T>(`/agents/${encodeURIComponent(agentName)}/voice/${path}`, {
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
  config?: SettingDef[];
  config_label?: string;
  options?: {
    value: string;
    label: string;
    preview?: string;
    custom?: boolean;
    [k: string]: unknown;
  }[];
}

export const setVoiceSetting = (
  n: string,
  domain: "stt" | "tts",
  key: string,
  value: unknown,
): Promise<SttStatus | TtsStatus> =>
  voicePost<SttStatus | TtsStatus>(n, `${domain}/set`, { key, value });

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

function ttsStreamUrl(agentName: string, id: string): Promise<string> {
  return authedUrl(
    `/agents/${encodeURIComponent(agentName)}/voice/tts/stream/${encodeURIComponent(id)}`,
  );
}

import type { AudioCapture, SpeechPlayer, VoiceSocketLike } from "@vesta/core";

// The SpeechPlayer port the TTS queue drives: prepare registers the text, play streams one
// prepared utterance through a native <audio> element (the media stack streams from the first
// byte on every webview and owns Bluetooth routing).
export function browserPlayer(agentName: () => string | null): SpeechPlayer {
  return {
    prepare: (text) => {
      const name = agentName();
      if (!name) return Promise.reject(new Error("no agent selected"));
      return prepareSpeech(text, name);
    },
    play: async (id, signal) => {
      const name = agentName();
      if (!name || signal.aborted) return;
      const src = await ttsStreamUrl(name, id);
      const audio = new Audio(src);
      audio.preload = "auto";
      await new Promise<void>((resolve, reject) => {
        const cleanup = () => {
          audio.onended = null;
          audio.onerror = null;
        };
        // Resolve (not reject) on abort so the queue's await completes instead of hanging
        // when playback is cancelled mid-stream.
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
    },
  };
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

// --- STT capture and socket (the ports the shared STT session drives) ---

export function voiceWsUrl(agentName: string): Promise<string> {
  return websocketUrl(
    `/agents/${encodeURIComponent(agentName)}/voice/stt/listen`,
  );
}

// The socket port over a browser WebSocket. The shared session assigns the callbacks
// synchronously after this returns, before the browser can fire an event, so no open is lost.
export function browserSocket(url: string): VoiceSocketLike {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  const adapter: VoiceSocketLike = {
    send: (data) => {
      try {
        ws.send(data);
      } catch {
        // socket may have closed between the session's check and this send — ignore
      }
    },
    close: () => {
      try {
        ws.close();
      } catch {
        /* already closed */
      }
    },
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  ws.onopen = () => adapter.onopen?.();
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") adapter.onmessage?.(ev.data);
  };
  ws.onclose = (ev) => adapter.onclose?.(ev.reason);
  return adapter;
}

// The microphone port: raw 16 kHz mono PCM frames to onFrame until stopped. `muted` is read
// per frame; a muted mic streams silence rather than nothing, so the STT stream stays alive
// and a turn caught mid-sentence still gets its end (which releases the yield-to-user gate).
export function browserCapture(muted?: () => boolean): AudioCapture {
  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;

  const teardown = (): void => {
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

  return {
    start: async (onFrame) => {
      if (!("mediaDevices" in navigator))
        throw new Error("Microphone requires a secure connection");
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
        await audioCtx.audioWorklet.addModule(WORKLET_URL);
      } catch {
        teardown();
        throw new Error("Could not initialize audio capture");
      }
      const source = audioCtx.createMediaStreamSource(stream);
      const workletNode = new AudioWorkletNode(audioCtx, "pcm-processor", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
      });
      workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
        if (muted?.()) e.data.fill(0);
        onFrame(floatTo16BitPCM(e.data));
      };
      source.connect(workletNode);
      workletNode.connect(audioCtx.destination);
    },
    stop: teardown,
  };
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
