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
  ttsStreamPath,
  voicePlayPath,
  voiceSessionPath,
} from "@vesta/core";
import { fetchVoiceStatus, prepareSpeech } from "@vesta/core";
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
  onTranscript: (text: string) => void;
  onSend: (text: string) => void;
  onError: (message: string) => void;
  onInactivityStop: () => void;
  // Forwarded to the chat socket, so the agent holds its reply while the user is talking.
  onUserSpeakingChange: (speaking: boolean) => void;
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

// The mobile adapter over @vesta/core's voice session: expo-audio capture and playback as the
// ports, the session as the behavior (dictation vs conversation, the plays of the engine). A
// conversation additionally holds the native hands-free session (Bluetooth routing, echo
// cancellation, and the Android microphone foreground service) around the microphone.
export function useLiveVoice({
  name,
  enabled,
  onTranscript,
  onSend,
  onError,
  onInactivityStop,
  onUserSpeakingChange,
}: LiveVoiceOptions) {
  const { api } = useSession();
  const [recordingMode, setRecordingMode] = useState<VoiceMode | null>(null);
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  // A muted mic streams silence rather than nothing, so the session stays up.
  const [micMuted, setMicMuted] = useState(false);
  const micMutedRef = useRef(false);

  // Live-updated refs, so the session (created once per agent) always reads the current
  // callbacks and settings.
  const callbacksRef = useRef({
    onTranscript,
    onSend,
    onError,
    onInactivityStop,
    onUserSpeakingChange,
  });
  const ttsEnabledRef = useRef(false);

  const frameSinkRef = useRef<((pcm: ArrayBuffer) => void) | null>(null);
  const permissionGrantedRef = useRef(false);
  const sessionRef = useRef<VoiceSession | null>(null);

  const { stream } = useAudioStream({
    sampleRate: 16_000,
    channels: 1,
    encoding: "int16",
    onBuffer: (buffer) => {
      const pcm = buffer.data.slice(0);
      if (micMutedRef.current) new Uint8Array(pcm).fill(0);
      frameSinkRef.current?.(pcm);
    },
  });
  const streamRef = useRef(stream);

  const player = useAudioPlayer(null);
  const playerRef = useRef(player);

  useEffect(() => {
    callbacksRef.current = {
      onTranscript,
      onSend,
      onError,
      onInactivityStop,
      onUserSpeakingChange,
    };
    ttsEnabledRef.current = ttsEnabled;
    micMutedRef.current = micMuted;
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

  // Created in an effect rather than during render: the session's ports close over refs, and
  // only post-render code may read them.
  useEffect(() => {
    const releaseCapture = () => {
      frameSinkRef.current = null;
      streamRef.current.stop();
      void setRecordingHapticsEnabled(false).catch(() => undefined);
      void setHandsFreeSessionActive(false).catch(() => undefined);
      void stopVoiceForegroundService().catch(() => undefined);
      void setAudioModeAsync(PLAYBACK_AUDIO_MODE).catch(() => undefined);
    };
    const play = async (
      url: string,
      signal: AbortSignal,
      onStarted: () => void,
    ) => {
      if (signal.aborted) return;
      const target = playerRef.current;
      await new Promise<void>((resolve) => {
        // The source dropping out of a loaded/buffering state after it started is a failed or
        // interrupted stream. Settling on that (as well as a natural finish and abort) keeps
        // the queue advancing instead of blocking on a promise that never settles. A source
        // that errors before it ever loads emits no such transition; the caller aborts a
        // play whose sound does not start in time.
        let started = false;
        let sounded = false;
        const settle = () => {
          subscription.remove();
          resolve();
        };
        const subscription = target.addListener(
          "playbackStatusUpdate",
          (status) => {
            if (status.isLoaded || status.isBuffering || status.playing)
              started = true;
            // The first sound of this url: a resume after a pause plays again and is no start.
            if (status.playing && !sounded) {
              sounded = true;
              onStarted();
            }
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
    };

    const session = createVoiceSession(
      {
        buildUrl: () => api.websocketUrl(voiceSessionPath(name)),
        // The voice session stops the port again once a start that a stop overtook settles,
        // so a stop during these awaits needs no guard here.
        capture: {
          start: async (onFrame) => {
            if (!permissionGrantedRef.current) {
              const permission = await requestRecordingPermissionsAsync();
              if (!permission.granted)
                throw new Error(
                  "Microphone permission is needed for live voice.",
                );
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
          stop: releaseCapture,
        },
        speaker: {
          play,
          pause: () => {
            playerRef.current.pause();
          },
          resume: () => {
            playerRef.current.play();
          },
        },
        playUrl: (path) => api.authedUrl(voicePlayPath(name, path)),
        // A reply read aloud outside a session: the text is registered, then streamed.
        prepareSpeech: async (text) =>
          api.authedUrl(
            ttsStreamPath(name, await prepareSpeech(api, name, text)),
          ),
        client: "mobile",
      },
      {
        onTranscript: (text) => callbacksRef.current.onTranscript(text),
        onSend: (text) => callbacksRef.current.onSend(text),
        onError: (message) => callbacksRef.current.onError(message),
        onModeChange: (mode) => {
          setRecordingMode(mode);
          if (mode === null) setMicMuted(false);
        },
        onListeningChange: setListening,
        onSpeakingChange: setSpeaking,
        onUserSpeakingChange: (speaking) =>
          callbacksRef.current.onUserSpeakingChange(speaking),
        onInactivityStop: () => callbacksRef.current.onInactivityStop(),
      },
      () => ({ inactivityMs: CONVERSATION_INACTIVITY_MS }),
    );
    sessionRef.current = session;
    return () => {
      sessionRef.current = null;
      session.cancel();
      session.stopSpeech();
    };
  }, [api, name]);

  const start = useCallback(
    (mode: VoiceMode) => sessionRef.current?.start(mode) ?? Promise.resolve(),
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
    micMuted,
    toggleMicMuted: () => setMicMuted((muted) => !muted),
    start,
    stop,
    cancel,
    speak,
    prefetch,
    stopSpeech,
  };
}
