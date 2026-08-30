import { useCallback, useEffect, useRef, useState } from "react";
import {
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioStream,
} from "expo-audio";
import {
  createVoiceSession,
  type VoiceMode,
  type VoiceSession,
  type VoiceSocketLike,
} from "@vesta/core";
import { fetchVoiceStatus, prepareSpeech } from "@/api/endpoints";
import type { SettingDef, VoiceStatus } from "@/api/types";
import { useSession } from "@/session/SessionProvider";
import { setHandsFreeSessionActive } from "@/voice/hands-free-session";
import { setRecordingHapticsEnabled } from "@/voice/recording-haptics";
import {
  startVoiceForegroundService,
  stopVoiceForegroundService,
} from "@/voice/voice-service";

interface LiveVoiceOptions {
  name: string;
  enabled: boolean;
  sttStatus: VoiceStatus | null;
  onTranscript: (text: string) => void;
  onSend: (text: string) => void;
  onError: (message: string) => void;
  onInactivityStop: () => void;
}

// A conversation with no user turn for this long ends itself, bounding the battery and
// transcription spend of a session the user forgot.
const CONVERSATION_INACTIVITY_MS = 15 * 60_000;

const RECORDING_AUDIO_MODE = {
  allowsRecording: true,
  playsInSilentMode: true,
  interruptionMode: "doNotMix",
} as const;
// Restored when a listening session ends, so playback-only use never keeps the
// record-category audio session active.
const PLAYBACK_AUDIO_MODE = {
  allowsRecording: false,
  playsInSilentMode: true,
} as const;

function boolSetting(
  status: VoiceStatus | null,
  key: string,
  fallback: boolean,
): boolean {
  const value = status?.settings?.find((s: SettingDef) => s.key === key)?.value;
  return typeof value === "boolean" ? value : fallback;
}

function createVoiceSocket(url: string): VoiceSocketLike {
  const socket = new WebSocket(url);
  socket.binaryType = "arraybuffer";
  const like: VoiceSocketLike = {
    send: (data) => {
      try {
        socket.send(data);
      } catch {
        // socket may have closed between the session's check and this send — ignore
      }
    },
    close: () => socket.close(),
    onopen: null,
    onmessage: null,
    onclose: null,
  };
  socket.onopen = () => like.onopen?.();
  socket.onmessage = (message) => {
    if (typeof message.data === "string") like.onmessage?.(message.data);
  };
  socket.onclose = (event) => like.onclose?.(event.reason);
  return like;
}

// The mobile adapter over @vesta/core's voice session: expo-audio capture and playback as the
// ports, the session as the behavior (dictation vs conversation, barge-in, the TTS queue). A
// conversation additionally holds the native hands-free session (Bluetooth routing, echo
// cancellation, and the Android microphone foreground service) around the microphone.
export function useLiveVoice({
  name,
  enabled,
  sttStatus,
  onTranscript,
  onSend,
  onError,
  onInactivityStop,
}: LiveVoiceOptions) {
  const { api } = useSession();
  const [recordingMode, setRecordingMode] = useState<VoiceMode | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);

  // Live-updated refs, so the session (created once per agent) always reads the current
  // callbacks and settings.
  const callbacksRef = useRef({ onTranscript, onSend, onError, onInactivityStop });
  const sttStatusRef = useRef(sttStatus);
  const ttsEnabledRef = useRef(false);

  const frameSinkRef = useRef<((pcm: ArrayBuffer) => void) | null>(null);
  const permissionGrantedRef = useRef(false);
  const sessionRef = useRef<VoiceSession | null>(null);

  const { stream } = useAudioStream({
    sampleRate: 16_000,
    channels: 1,
    encoding: "int16",
    onBuffer: (buffer) => frameSinkRef.current?.(buffer.data.slice(0)),
  });
  const streamRef = useRef(stream);

  const player = useAudioPlayer(null);
  const playerRef = useRef(player);

  useEffect(() => {
    callbacksRef.current = { onTranscript, onSend, onError, onInactivityStop };
    sttStatusRef.current = sttStatus;
    ttsEnabledRef.current = ttsEnabled;
    streamRef.current = stream;
    playerRef.current = player;
  });

  useEffect(() => {
    let live = true;
    void fetchVoiceStatus(api, name, "tts")
      .then((status) => {
        if (live) setTtsEnabled(status.configured && status.enabled !== false);
      })
      .catch(() => {
        if (live) setTtsEnabled(false);
      });
    return () => {
      live = false;
    };
  }, [api, name]);

  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void getRecordingPermissionsAsync()
      .then((permission) => {
        if (live && permission.granted) permissionGrantedRef.current = true;
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [enabled]);

  const playPrepared = useCallback(
    async (identifier: string, signal: AbortSignal) => {
      const url = await api.authedUrl(
        `/agents/${encodeURIComponent(name)}/voice/tts/stream/${encodeURIComponent(identifier)}`,
      );
      if (signal.aborted) return;
      const target = playerRef.current;
      await new Promise<void>((resolve) => {
        // The source dropping out of a loaded/buffering state after it started is a failed or
        // interrupted stream. Settling on that (as well as a natural finish and abort) keeps
        // the queue advancing instead of blocking on a promise that never settles. A source
        // that errors before it ever loads emits no such transition; that reply is silent
        // until the next stopSpeech or barge-in aborts it, which every conversation turn does.
        let started = false;
        const settle = () => {
          subscription.remove();
          resolve();
        };
        const subscription = target.addListener(
          "playbackStatusUpdate",
          (status) => {
            if (status.isLoaded || status.isBuffering || status.playing)
              started = true;
            if (
              status.didJustFinish ||
              (started && !status.isLoaded && !status.isBuffering)
            )
              settle();
          },
        );
        signal.addEventListener("abort", () => {
          target.pause();
          settle();
        });
        target.replace(url);
        target.play();
      });
    },
    [api, name],
  );

  // Created in an effect rather than during render: the session's ports close over refs, and
  // only post-render code may read them.
  useEffect(() => {
    const session = createVoiceSession(
      {
        buildUrl: () =>
          api.websocketUrl(
            `/agents/${encodeURIComponent(name)}/voice/stt/listen`,
          ),
        createSocket: createVoiceSocket,
        capture: {
          start: async (onFrame) => {
            if (!permissionGrantedRef.current) {
              const permission = await requestRecordingPermissionsAsync();
              if (!permission.granted)
                throw new Error("Microphone permission is needed for live voice.");
              permissionGrantedRef.current = true;
            }
            await setAudioModeAsync(RECORDING_AUDIO_MODE);
            if (sessionRef.current?.mode() === "conversation") {
              // After the expo-audio mode so the native override wins: voice processing plus
              // Bluetooth routing on iOS, and the microphone foreground service that keeps a
              // locked-screen mic alive on Android.
              await setHandsFreeSessionActive(true);
              await startVoiceForegroundService(
                "Voice session",
                `${name} is listening`,
              );
            }
            frameSinkRef.current = onFrame;
            await streamRef.current.start();
            await setRecordingHapticsEnabled(true).catch(() => undefined);
          },
          stop: () => {
            frameSinkRef.current = null;
            streamRef.current.stop();
            void setRecordingHapticsEnabled(false).catch(() => undefined);
            void setHandsFreeSessionActive(false).catch(() => undefined);
            void stopVoiceForegroundService().catch(() => undefined);
            void setAudioModeAsync(PLAYBACK_AUDIO_MODE).catch(() => undefined);
          },
        },
        player: {
          prepare: (text) => prepareSpeech(api, name, text),
          play: playPrepared,
        },
        setTimer: (fn, ms) => setTimeout(fn, ms) as unknown as number,
        clearTimer: (handle) => clearTimeout(handle),
      },
      {
        onTranscript: (text) => callbacksRef.current.onTranscript(text),
        onSend: (text) => callbacksRef.current.onSend(text),
        onError: (message) => callbacksRef.current.onError(message),
        onModeChange: setRecordingMode,
        onListeningChange: setListening,
        onSpeakingChange: setSpeaking,
        onInactivityStop: () => callbacksRef.current.onInactivityStop(),
      },
      () => ({
        interruptTts: boolSetting(sttStatusRef.current, "interrupt_tts", true),
        inactivityMs: CONVERSATION_INACTIVITY_MS,
      }),
    );
    sessionRef.current = session;
    return () => {
      sessionRef.current = null;
      session.cancel();
      session.stopSpeech();
    };
  }, [api, name, playPrepared]);

  const start = useCallback(
    (mode: VoiceMode) =>
      sessionRef.current?.start(mode) ?? Promise.resolve(),
    [],
  );
  const stop = useCallback(() => sessionRef.current?.stop(), []);
  const cancel = useCallback(() => sessionRef.current?.cancel(), []);
  const speak = useCallback((text: string) => {
    if (ttsEnabledRef.current) sessionRef.current?.speak(text);
  }, []);
  const prefetch = useCallback((text: string) => {
    if (ttsEnabledRef.current) sessionRef.current?.prefetch(text);
  }, []);
  const stopSpeech = useCallback(() => sessionRef.current?.stopSpeech(), []);

  return {
    recordingMode,
    listening,
    speaking,
    ttsEnabled,
    start,
    stop,
    cancel,
    speak,
    prefetch,
    stopSpeech,
  };
}
