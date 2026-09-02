import * as core from "@vesta/core";
import type { AudioCapture, SpeechPlayer } from "@vesta/core";
import { authedUrl, httpClient, websocketUrl } from "@/api/client";

const SAMPLE_RATE = 16000;

// The voice routes live once in @vesta/core; these bind the app's one HttpClient so call sites
// keep their names. The status shape is one type for both domains.
export type { SettingDef, SttUsage, TtsUsage } from "@vesta/core";
export type SttStatus = core.VoiceStatus;
export type TtsStatus = core.VoiceStatus;

export const setVoiceSetting = (
  n: string,
  domain: core.VoiceDomain,
  key: string,
  value: unknown,
): Promise<SttStatus> =>
  core.setVoiceSetting(httpClient, n, domain, key, value);

export const fetchSttStatus = (agentName: string, signal?: AbortSignal) =>
  core.fetchVoiceStatus(httpClient, agentName, "stt", signal);
export const fetchSttUsage = (agentName: string) =>
  core.fetchSttUsage(httpClient, agentName);
export const setSttEnabled = (n: string, value: boolean) =>
  core.setVoiceEnabled(httpClient, n, "stt", value);

export const fetchTtsStatus = (agentName: string, signal?: AbortSignal) =>
  core.fetchVoiceStatus(httpClient, agentName, "tts", signal);
export const fetchTtsUsage = (agentName: string) =>
  core.fetchTtsUsage(httpClient, agentName);
export const setTtsEnabled = (n: string, value: boolean) =>
  core.setVoiceEnabled(httpClient, n, "tts", value);

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
  return core.prepareSpeech(httpClient, agentName, text, signal);
}

function ttsStreamUrl(agentName: string, id: string): Promise<string> {
  return authedUrl(core.ttsStreamPath(agentName, id));
}

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
  return websocketUrl(core.sttListenPath(agentName));
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
