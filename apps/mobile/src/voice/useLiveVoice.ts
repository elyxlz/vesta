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
  serviceKeyQueryUrl,
  serviceKeySocketUrl,
  voiceBoolSetting,
  type VoiceSession,
  type VoiceSocketLike,
} from "@vesta/core";
import { fetchVoiceStatus, prepareSpeech } from "@/api/endpoints";
import type { VoiceStatus } from "@/api/types";
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
}

// A conversation with no user turn for this long ends itself, bounding the
// battery and transcription spend of a session the user forgot.
const CONVERSATION_IDLE_STOP_MS = 10 * 60_000;

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

function createVoiceSocket(url: string): VoiceSocketLike {
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
  socket.onmessage = (message) => {
    if (typeof message.data === "string") like.onmessage?.(message.data);
  };
  socket.onclose = (event) => like.onclose?.(event.reason);
  return like;
}

// The mobile adapter over @vesta/core's voice session: expo-audio capture and
// playback as the ports, the session as the behavior (barge-in, auto-send
// routing, the TTS queue).
export function useLiveVoice({
  name,
  enabled,
  sttStatus,
  onTranscript,
  onSend,
  onError,
}: LiveVoiceOptions) {
  const { api } = useSession();
  const [active, setActive] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);

  // Live-updated refs, so the session (created once per agent) always reads
  // the current callbacks and settings.
  const callbacksRef = useRef({ onTranscript, onSend, onError });
  const sttStatusRef = useRef(sttStatus);
  const ttsEnabledRef = useRef(false);

  const frameSinkRef = useRef<((pcm: ArrayBuffer) => void) | null>(null);
  const permissionGrantedRef = useRef(false);
  // Hands-free conversation: forces auto-send and barge-in, arms the idle
  // auto-stop, and holds the native session (Bluetooth routing, echo
  // cancellation, the Android foreground service) around the microphone.
  const conversationRef = useRef(false);

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
    callbacksRef.current = { onTranscript, onSend, onError };
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
      const connection = api.getConnection();
      if (!connection) return;
      const key = await api.serviceKeys.get(name, "voice");
      // The player streams a keyed GET: a media element sends no header.
      const url = serviceKeyQueryUrl(
        connection.url,
        name,
        "voice",
        key,
        `/tts/stream/${encodeURIComponent(identifier)}`,
      );
      if (signal.aborted) return;
      const target = playerRef.current;
      await new Promise<void>((resolve) => {
        const subscription = target.addListener(
          "playbackStatusUpdate",
          (status) => {
            if (status.didJustFinish) {
              subscription.remove();
              resolve();
            }
          },
        );
        signal.addEventListener("abort", () => {
          subscription.remove();
          target.pause();
          resolve();
        });
        target.replace(url);
        target.play();
      });
    },
    [api, name],
  );

  // Created in an effect rather than during render: the session's ports close
  // over refs, and only post-render code may read them.
  const sessionRef = useRef<VoiceSession | null>(null);
  useEffect(() => {
    const session = createVoiceSession(
      {
        buildUrl: async () => {
          const connection = api.getConnection();
          if (!connection) throw new Error("Not connected to a Vesta gateway.");
          const key = await api.serviceKeys.get(name, "voice");
          return serviceKeySocketUrl(
            connection.url,
            name,
            "voice",
            key,
            "/stt/listen",
          );
        },
        createSocket: createVoiceSocket,
        capture: {
          start: async (onFrame) => {
            if (!permissionGrantedRef.current) {
              const permission = await requestRecordingPermissionsAsync();
              if (!permission.granted) {
                throw new Error(
                  "Microphone permission is needed for live voice.",
                );
              }
              permissionGrantedRef.current = true;
            }
            await setAudioModeAsync(RECORDING_AUDIO_MODE);
            if (conversationRef.current) {
              // After the expo-audio mode so the native override wins: voice
              // processing plus Bluetooth routing on iOS, and the microphone
              // foreground service that keeps a locked-screen mic alive on
              // Android.
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
            if (conversationRef.current) {
              void setHandsFreeSessionActive(false).catch(() => undefined);
              void stopVoiceForegroundService().catch(() => undefined);
            }
            void setAudioModeAsync(PLAYBACK_AUDIO_MODE).catch(() => undefined);
          },
        },
        player: {
          prepare: (text) => prepareSpeech(api, name, text),
          play: playPrepared,
        },
        setTimer: (fn, ms) => setTimeout(fn, ms),
        clearTimer: (handle) => clearTimeout(handle),
      },
      {
        onTranscript: (text) => callbacksRef.current.onTranscript(text),
        onSend: (text) => callbacksRef.current.onSend(text),
        // The composer is both the live-transcript display and the draft box,
        // so an unsent turn lands there through the same sink.
        onDraft: (text) => callbacksRef.current.onTranscript(text),
        onError: (message) => callbacksRef.current.onError(message),
        onListeningChange: setActive,
        onSpeakingChange: setSpeaking,
      },
      () =>
        conversationRef.current
          ? {
              autoSend: true,
              interruptTts: true,
              hold: false,
              idleTimeoutMs: CONVERSATION_IDLE_STOP_MS,
            }
          : {
              autoSend: voiceBoolSetting(
                sttStatusRef.current,
                "auto_send",
                true,
              ),
              interruptTts: voiceBoolSetting(
                sttStatusRef.current,
                "interrupt_tts",
                true,
              ),
              hold: false,
              idleTimeoutMs: 0,
            },
    );
    sessionRef.current = session;
    return () => {
      sessionRef.current = null;
      session.stopListening();
      session.stopSpeech();
      conversationRef.current = false;
    };
  }, [api, name, playPrepared]);

  const start = useCallback(
    () => sessionRef.current?.startListening() ?? Promise.resolve(),
    [],
  );
  const stop = useCallback(() => {
    sessionRef.current?.stopListening();
  }, []);
  const startConversation = useCallback(async () => {
    // A dictation session in flight would keep its captured non-conversation
    // idle setting and skip the native hands-free setup, so end it first.
    sessionRef.current?.stopListening();
    conversationRef.current = true;
    try {
      await sessionRef.current?.startListening();
    } catch (cause) {
      conversationRef.current = false;
      throw cause;
    }
  }, []);
  const stopConversation = useCallback(() => {
    sessionRef.current?.stopListening();
    sessionRef.current?.stopSpeech();
    conversationRef.current = false;
  }, []);
  const speak = useCallback((text: string) => {
    if (ttsEnabledRef.current) sessionRef.current?.speak(text);
  }, []);
  const prefetch = useCallback((text: string) => {
    if (ttsEnabledRef.current) sessionRef.current?.prefetch(text);
  }, []);
  const stopSpeech = useCallback(() => {
    sessionRef.current?.stopSpeech();
  }, []);

  return {
    active,
    speaking,
    ttsEnabled,
    start,
    stop,
    startConversation,
    stopConversation,
    speak,
    prefetch,
    stopSpeech,
  };
}
