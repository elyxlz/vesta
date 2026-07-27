import { useCallback, useEffect, useRef, useState } from "react";
import {
  getRecordingPermissionsAsync,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioStream,
} from "expo-audio";
import { serviceKeyQueryUrl } from "@vesta/core";
import type { ApiClient } from "@/api/client";
import { fetchVoiceStatus, prepareSpeech } from "@/api/endpoints";
import { useSession } from "@/session/SessionProvider";
import { setRecordingHapticsEnabled } from "@/voice/recording-haptics";

interface TurnInfo {
  type?: string;
  event?: string;
  transcript?: string;
}

interface LiveVoiceOptions {
  name: string;
  enabled: boolean;
  onTranscript: (text: string) => void;
  onTurnEnd: () => void;
  onError: (message: string) => void;
}

const MAX_PENDING_AUDIO_BYTES = 16_000 * 2 * 2;
const RECORDING_AUDIO_MODE = {
  allowsRecording: true,
  playsInSilentMode: true,
  interruptionMode: "doNotMix",
} as const;

export function useLiveVoice({
  name,
  enabled,
  onTranscript,
  onTurnEnd,
  onError,
}: LiveVoiceOptions) {
  const { api } = useSession();
  const socketRef = useRef<WebSocket | null>(null);
  const mountedRef = useRef(true);
  const activeRef = useRef(false);
  const sessionRef = useRef(0);
  const permissionGrantedRef = useRef(false);
  const audioModeReadyRef = useRef(false);
  const audioModePromiseRef = useRef<Promise<void> | null>(null);
  const pendingAudioRef = useRef<ArrayBuffer[]>([]);
  const pendingAudioBytesRef = useRef(0);
  const [active, setActive] = useState(false);

  const clearPendingAudio = useCallback(() => {
    pendingAudioRef.current = [];
    pendingAudioBytesRef.current = 0;
  }, []);

  const prepareAudioMode = useCallback(async (): Promise<void> => {
    if (audioModeReadyRef.current) return;
    let pending = audioModePromiseRef.current;
    if (!pending) {
      pending = setAudioModeAsync(RECORDING_AUDIO_MODE)
        .then(() => {
          audioModeReadyRef.current = true;
        })
        .finally(() => {
          audioModePromiseRef.current = null;
        });
      audioModePromiseRef.current = pending;
    }
    await pending;
  }, []);

  const flushPendingAudio = useCallback((socket: WebSocket) => {
    const pending = pendingAudioRef.current;
    pendingAudioRef.current = [];
    pendingAudioBytesRef.current = 0;
    for (const data of pending) socket.send(data);
  }, []);

  const { stream } = useAudioStream({
    sampleRate: 16_000,
    channels: 1,
    encoding: "int16",
    onBuffer: (buffer) => {
      if (!activeRef.current) return;
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) {
        socket.send(buffer.data);
        return;
      }

      const data = buffer.data.slice(0);
      while (
        pendingAudioRef.current.length > 0 &&
        pendingAudioBytesRef.current + data.byteLength >
          MAX_PENDING_AUDIO_BYTES
      ) {
        const discarded = pendingAudioRef.current.shift();
        pendingAudioBytesRef.current -= discarded?.byteLength ?? 0;
      }
      if (data.byteLength <= MAX_PENDING_AUDIO_BYTES) {
        pendingAudioRef.current.push(data);
        pendingAudioBytesRef.current += data.byteLength;
      }
    },
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeRef.current = false;
      sessionRef.current += 1;
      clearPendingAudio();
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
      void setRecordingHapticsEnabled(false).catch(() => undefined);
    };
  }, [clearPendingAudio]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void getRecordingPermissionsAsync()
      .then(async (permission) => {
        if (cancelled || !permission.granted) return;
        permissionGrantedRef.current = true;
        await prepareAudioMode();
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enabled, prepareAudioMode]);

  const stop = useCallback(() => {
    if (!mountedRef.current) return;
    sessionRef.current += 1;
    activeRef.current = false;
    setActive(false);
    clearPendingAudio();
    const socket = socketRef.current;
    socketRef.current = null;
    stream.stop();
    void setRecordingHapticsEnabled(false).catch(() => undefined);
    socket?.close();
    onTurnEnd();
  }, [clearPendingAudio, onTurnEnd, stream]);

  const start = useCallback(async (): Promise<void> => {
    if (activeRef.current || !mountedRef.current) return;
    const session = sessionRef.current + 1;
    sessionRef.current = session;
    activeRef.current = true;
    setActive(true);
    onTranscript("");
    clearPendingAudio();

    const isCurrent = () =>
      mountedRef.current &&
      activeRef.current &&
      sessionRef.current === session;

    try {
      if (!permissionGrantedRef.current) {
        const permission = await requestRecordingPermissionsAsync();
        if (!isCurrent()) return;
        if (!permission.granted) {
          activeRef.current = false;
          setActive(false);
          onError("Microphone permission is needed for live voice.");
          return;
        }
        permissionGrantedRef.current = true;
      }

      await prepareAudioMode();
      if (!isCurrent()) return;

      const connection = api.getConnection();
      if (!connection) throw new Error("Not connected to a Vesta gateway.");
      const key = await api.serviceKeys.get(name, "voice");
      if (!isCurrent()) return;

      const socket = new WebSocket(
        serviceKeyQueryUrl(
          connection.url.replace(/^http/, "ws"),
          name,
          "voice",
          key,
          "/stt/listen",
        ),
      );
      socket.binaryType = "arraybuffer";
      socketRef.current = socket;

      let opened = false;
      const socketReady = new Promise<void>((resolve, reject) => {
        socket.onopen = () => {
          if (!isCurrent()) {
            socket.close();
            reject(new Error("Live transcription start was cancelled."));
            return;
          }
          opened = true;
          flushPendingAudio(socket);
          resolve();
        };
        socket.onerror = () => {
          if (!opened) {
            reject(new Error("Could not connect to live transcription."));
            return;
          }
          if (!isCurrent()) return;
          onError("Connection to live transcription was lost.");
          stop();
        };
        socket.onclose = (event) => {
          if (!opened) {
            reject(
              new Error(
                event.reason || "Live transcription closed before starting.",
              ),
            );
            return;
          }
          if (!isCurrent() || socketRef.current !== socket) return;
          socketRef.current = null;
          activeRef.current = false;
          clearPendingAudio();
          stream.stop();
          void setRecordingHapticsEnabled(false).catch(() => undefined);
          setActive(false);
        };
      });

      socket.onmessage = (message) => {
        if (!isCurrent() || typeof message.data !== "string") return;
        let event: TurnInfo;
        try {
          event = JSON.parse(message.data);
        } catch {
          return;
        }
        if (event.type === "TurnInfo") {
          if (event.transcript !== undefined) {
            onTranscript(event.transcript);
          }
          if (event.event === "EndOfTurn") {
            onTurnEnd();
          }
        } else if (
          event.type === "ConfigureFailure" ||
          event.type === "Error"
        ) {
          onError("The transcription service reported an error.");
          stop();
        }
      };

      const captureReady = stream.start().then(() =>
        setRecordingHapticsEnabled(true).catch(() => undefined),
      );
      await Promise.all([captureReady, socketReady]);
    } catch (cause) {
      if (!isCurrent()) return;
      activeRef.current = false;
      setActive(false);
      clearPendingAudio();
      stream.stop();
      void setRecordingHapticsEnabled(false).catch(() => undefined);
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
      throw cause;
    }
  }, [
    api,
    clearPendingAudio,
    flushPendingAudio,
    name,
    onError,
    onTranscript,
    onTurnEnd,
    prepareAudioMode,
    stop,
    stream,
  ]);

  return { start, stop, active };
}

// The URL the audio player streams a prepared utterance from, carrying a minted service key:
// a media element sends no header. Null when the session has no gateway to stream from.
async function ttsStreamUrl(
  api: ApiClient,
  name: string,
  identifier: string,
): Promise<string | null> {
  const connection = api.getConnection();
  if (!connection) return null;
  const key = await api.serviceKeys.get(name, "voice");
  return serviceKeyQueryUrl(
    connection.url,
    name,
    "voice",
    key,
    `/tts/stream/${encodeURIComponent(identifier)}`,
  );
}

export function useSpeechPlayer(name: string, latestText: string | null) {
  const { api } = useSession();
  const player = useAudioPlayer(null);
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchVoiceStatus(api, name, "tts")
      .then((status) => {
        if (active) setEnabled(status.configured && status.enabled !== false);
      })
      .catch(() => {
        if (active) setEnabled(false);
      });
    return () => {
      active = false;
    };
  }, [api, name]);

  useEffect(() => {
    if (!enabled || !latestText) return;
    let active = true;
    void prepareSpeech(api, name, latestText).then(async (identifier) => {
      if (!active) return;
      const url = await ttsStreamUrl(api, name, identifier);
      if (!active || !url) return;
      player.replace(url);
      player.play();
    });
    return () => {
      active = false;
    };
  }, [api, enabled, latestText, name, player]);

  const play = useCallback(
    async (text: string): Promise<void> => {
      if (!enabled || !text.trim()) return;
      if (!api.getConnection()) return;
      const identifier = await prepareSpeech(api, name, text);
      const url = await ttsStreamUrl(api, name, identifier);
      if (!url) return;
      player.replace(url);
      player.play();
    },
    [api, enabled, name, player],
  );

  return {
    stop: () => player.pause(),
    play,
    enabled,
  };
}
