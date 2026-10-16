import * as core from "@vesta/core";
import type { AudioCapture, Speaker } from "@vesta/core";
import { authedUrl, httpClient, websocketUrl } from "@/api/client";
import { runtimeInfo, type RuntimeInfo } from "@/lib/native";
// no-inline: an inlined data: worklet is refused by the desktop CSP (script-src 'self').
import WORKLET_URL from "./pcm-worklet.js?url&no-inline";

const SAMPLE_RATE = 16000;

// The voice routes live once in @vesta/core; these bind the app's one HttpClient so call sites
// keep their names. The status shape is one type for both domains.
export type {
  SettingDef,
  SttUsage,
  TtsUsage,
  VoiceBehaviors,
} from "@vesta/core";
export type SttStatus = core.VoiceStatus;
export type TtsStatus = core.VoiceStatus;

export const setVoiceSetting = (
  n: string,
  domain: core.VoiceDomain,
  key: string,
  value: unknown,
): Promise<SttStatus> =>
  core.setVoiceSetting(httpClient, n, domain, key, value);

export const setVoiceBehavior = (n: string, key: string, value: unknown) =>
  core.setVoiceBehavior(httpClient, n, key, value);

export const selectVoiceProvider = (
  n: string,
  domain: core.VoiceDomain,
  provider: string,
): Promise<SttStatus> =>
  core.selectVoiceProvider(httpClient, n, domain, provider);

export const fetchVoiceSettings = (agentName: string, signal?: AbortSignal) =>
  core.fetchVoiceSettings(httpClient, agentName, signal);

export const fetchSttUsage = (agentName: string) =>
  core.fetchSttUsage(httpClient, agentName);
export const setSttEnabled = (n: string, value: boolean) =>
  core.setVoiceEnabled(httpClient, n, "stt", value);

export const fetchTtsUsage = (agentName: string) =>
  core.fetchTtsUsage(httpClient, agentName);

export const setJudgeEnabled = (n: string, value: boolean) =>
  core.setVoiceEnabled(httpClient, n, "judge", value);
export const setTtsEnabled = (n: string, value: boolean) =>
  core.setVoiceEnabled(httpClient, n, "tts", value);

// Speech plays through a native <audio> element pointed at a streamed GET, not JS-fetched
// bytes fed to MediaSource: the native media stack streams from the first byte on every
// webview (Android's System WebView has no reliable MSE for raw audio/mpeg) and owns audio
// routing including Bluetooth A2DP cold-start (issue #466). A media-element request can't
// carry an Authorization header, so each url carries the access token in its query.

// The url of one play of a voice session, from the path the engine named.
export function voicePlayUrl(
  agentName: string,
  enginePath: string,
): Promise<string> {
  return authedUrl(core.voicePlayPath(agentName, enginePath));
}

// A reply read aloud outside a session: a media element uses GET (no body), so the text is
// first registered via POST /tts/prepare, and the element streams GET /tts/stream/{id}.
export async function prepareSpeechUrl(
  agentName: string,
  text: string,
): Promise<string> {
  const id = await core.prepareSpeech(httpClient, agentName, text);
  return authedUrl(core.ttsStreamPath(agentName, id));
}

// The speaker port: one <audio> element for each url, with the pause and resume the voice
// engine asks for during a barge-in.
export function browserSpeaker(): Speaker {
  let current: HTMLAudioElement | null = null;
  return {
    play: (url, signal, onStarted) => {
      if (signal.aborted) return Promise.resolve();
      const audio = new Audio(url);
      audio.preload = "auto";
      current = audio;
      return new Promise<void>((resolve, reject) => {
        const release = () => {
          audio.onplaying = null;
          audio.onended = null;
          audio.onerror = null;
          if (current === audio) current = null;
        };
        // Resolve (not reject) on abort so the queue's await completes instead of hanging
        // when playback is cancelled mid-stream.
        signal.addEventListener("abort", () => {
          release();
          audio.pause();
          audio.src = "";
          resolve();
        });
        // A resume after a pause fires this event again; only the first one is the start.
        audio.onplaying = () => {
          audio.onplaying = null;
          onStarted();
        };
        audio.onended = () => {
          release();
          resolve();
        };
        audio.onerror = () => {
          release();
          reject(new Error("Audio playback failed"));
        };
        // A pause or an abort before the first sound rejects this promise with AbortError,
        // which is no failure: the resume plays the element again.
        audio.play().catch((cause: unknown) => {
          if (cause instanceof DOMException && cause.name === "AbortError")
            return;
          release();
          reject(cause instanceof Error ? cause : new Error(String(cause)));
        });
      });
    },
    pause: () => {
      current?.pause();
    },
    resume: () => {
      current?.play().catch(() => {
        /* the play ended or was stopped while paused */
      });
    },
  };
}

// --- Audio preload ---

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

// --- Capture and the engine socket (the ports the shared voice session drives) ---

export function voiceWsUrl(agentName: string): Promise<string> {
  return websocketUrl(core.voiceSessionPath(agentName));
}

// Where the user turns a denied microphone back on. In the desktop app the OS gates it (and the
// app opens that settings page itself); in a browser, the site permission does.
export function microphoneDeniedMessage(
  runtime: Pick<RuntimeInfo, "isDesktopApp" | "platform">,
): string {
  if (!runtime.isDesktopApp)
    return "Microphone access is blocked. Allow it for this site in your browser settings.";
  if (runtime.platform === "macos")
    return "Microphone access is off. Turn on Vesta in System Settings > Privacy & Security > Microphone.";
  if (runtime.platform === "windows")
    return "Microphone access is off. Turn it on in Settings > Privacy & security > Microphone.";
  return "Microphone access was denied.";
}

// The microphone port: raw 16 kHz mono PCM frames to onFrame until stopped. `muted` is read
// per frame; a muted mic streams silence rather than nothing, so the session stays up and a
// turn caught mid-sentence still gets its end (which returns the floor to the agent).
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
      // Locals, because a stop can run during each await. The voice session stops the port
      // again once this start settles, which releases what it opened after that stop.
      let mic: MediaStream;
      try {
        mic = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
      } catch (err) {
        if (err instanceof DOMException) {
          if (err.name === "NotAllowedError")
            throw new Error(microphoneDeniedMessage(runtimeInfo), {
              cause: err,
            });
          if (err.name === "NotFoundError")
            throw new Error("No microphone found", { cause: err });
          if (err.name === "NotReadableError")
            throw new Error("Microphone is in use by another app", {
              cause: err,
            });
        }
        throw new Error("Could not access microphone", { cause: err });
      }
      stream = mic;
      let ctx: AudioContext;
      try {
        ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
        audioCtx = ctx;
        await ctx.audioWorklet.addModule(WORKLET_URL);
      } catch (err) {
        throw new Error("Could not initialize audio capture", { cause: err });
      }
      const source = ctx.createMediaStreamSource(mic);
      const workletNode = new AudioWorkletNode(ctx, "pcm-processor", {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        channelCount: 1,
      });
      workletNode.port.onmessage = (e: MessageEvent<Float32Array>) => {
        if (muted?.()) e.data.fill(0);
        onFrame(floatTo16BitPCM(e.data));
      };
      source.connect(workletNode);
      workletNode.connect(ctx.destination);
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
