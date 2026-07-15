import { useCallback, useEffect, useRef, useState } from "react";
import {
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioPlayer,
  useAudioStream,
} from "expo-audio";
import { fetchVoiceStatus, prepareSpeech } from "@/api/endpoints";
import { useSession } from "@/session/SessionProvider";

interface TurnInfo {
  type?: string;
  event?: string;
  transcript?: string;
}

interface LiveVoiceOptions {
  name: string;
  onTranscript: (text: string) => void;
  onTurnEnd: (text: string) => void;
  onError: (message: string) => void;
}

export function useLiveVoice({
  name,
  onTranscript,
  onTurnEnd,
  onError,
}: LiveVoiceOptions) {
  const { api } = useSession();
  const socketRef = useRef<WebSocket | null>(null);
  const transcriptRef = useRef("");
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const socket = socketRef.current;
      socketRef.current = null;
      socket?.close();
    };
  }, []);

  const { stream, isStreaming } = useAudioStream({
    sampleRate: 16_000,
    channels: 1,
    encoding: "int16",
    onBuffer: (buffer) => {
      const socket = socketRef.current;
      if (socket?.readyState === WebSocket.OPEN) socket.send(buffer.data);
    },
  });

  const stop = useCallback(() => {
    if (!mountedRef.current) return;
    const socket = socketRef.current;
    socketRef.current = null;
    stream.stop();
    socket?.close();
    const finalTranscript = transcriptRef.current.trim();
    if (finalTranscript) onTurnEnd(finalTranscript);
    transcriptRef.current = "";
    onTranscript("");
  }, [onTranscript, onTurnEnd, stream]);

  const start = useCallback(async (): Promise<void> => {
    if (isStreaming || !mountedRef.current) return;
    const permission = await requestRecordingPermissionsAsync();
    if (!mountedRef.current) return;
    if (!permission.granted) {
      onError("Microphone permission is needed for live voice.");
      return;
    }
    await setAudioModeAsync({
      allowsRecording: true,
      playsInSilentMode: true,
      interruptionMode: "doNotMix",
    });
    if (!mountedRef.current) return;
    const socket = new WebSocket(
      api.websocketUrl(`/agents/${encodeURIComponent(name)}/voice/stt/listen`),
    );
    socket.binaryType = "arraybuffer";
    socketRef.current = socket;
    try {
      await new Promise<void>((resolve, reject) => {
        socket.onopen = () => resolve();
        socket.onerror = () =>
          reject(new Error("Could not connect to live transcription."));
        socket.onclose = (event) =>
          reject(
            new Error(
              event.reason || "Live transcription closed before starting.",
            ),
          );
      });
    } catch (cause) {
      if (socketRef.current === socket) socketRef.current = null;
      socket.close();
      throw cause;
    }
    if (!mountedRef.current) {
      if (socketRef.current === socket) socketRef.current = null;
      socket.close();
      return;
    }
    socket.onmessage = (message) => {
      if (!mountedRef.current) return;
      if (typeof message.data !== "string") return;
      let event: TurnInfo;
      try {
        event = JSON.parse(message.data);
      } catch {
        return;
      }
      if (event.type === "TurnInfo") {
        if (event.event === "StartOfTurn") transcriptRef.current = "";
        if (event.transcript !== undefined) {
          transcriptRef.current = event.transcript;
          onTranscript(event.transcript);
        }
        if (event.event === "EndOfTurn") {
          const finalTranscript = transcriptRef.current.trim();
          transcriptRef.current = "";
          onTranscript("");
          if (finalTranscript) onTurnEnd(finalTranscript);
        }
      } else if (event.type === "ConfigureFailure" || event.type === "Error") {
        onError("The transcription service reported an error.");
        stop();
      }
    };
    socket.onerror = () => {
      if (!mountedRef.current) return;
      onError("Connection to live transcription was lost.");
      stop();
    };
    socket.onclose = () => {
      if (mountedRef.current && socketRef.current === socket) {
        socketRef.current = null;
        stream.stop();
      }
    };
    await stream.start();
  }, [api, isStreaming, name, onError, onTranscript, onTurnEnd, stop, stream]);

  return { start, stop, active: isStreaming };
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
    void prepareSpeech(api, name, latestText).then((identifier) => {
      if (!active) return;
      player.replace(
        api.mediaUrl(
          `/agents/${encodeURIComponent(name)}/voice/tts/stream/${encodeURIComponent(identifier)}`,
        ),
      );
      player.play();
    });
    return () => {
      active = false;
    };
  }, [api, enabled, latestText, name, player]);

  return {
    stop: () => player.pause(),
    enabled,
  };
}
