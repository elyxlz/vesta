import type { ChatMessage } from "./chat-stream-model";
import { parseChatEvent } from "../protocol/parse-chat";
import {
  createReconnectingSocket,
  type ReconnectingSocketDeps,
  type ReconnectPhase,
} from "../transport/reconnecting-socket";

export type ChatSocketState = ReconnectPhase;

export type ChatSocketDeps = ReconnectingSocketDeps;

export interface ChatSocketCallbacks {
  onEvent: (event: ChatMessage) => void;
  // Fires on every transition; the session reseeds the tail by id whenever it sees "open" (a
  // reconnect at least), which reconciles any gap the replay-free socket skipped.
  onStateChange: (state: ChatSocketState) => void;
}

export interface ChatSocket {
  // Reports whether the user is talking into a live voice conversation; the daemon holds the
  // agent's replies while it is true. The latest value is cached and a true is replayed on
  // reconnect open. With no open socket nothing is sent, which is the right answer: the daemon
  // ties the flag to the connection that set it and clears it when that connection drops.
  reportSpeaking: (speaking: boolean) => void;
  close: () => void;
}

// A replay-free socket over the shared reconnect machine: each inbound text frame is one
// ChatMessage, parsed at the boundary; the store holds the durable copy, so a reconnect self-heals
// by the session refetching the tail on "open".
export function createChatSocket(
  deps: ChatSocketDeps,
  callbacks: ChatSocketCallbacks,
): ChatSocket {
  let speaking = false;
  const speakingFrame = (): string =>
    JSON.stringify({ type: "speaking", active: speaking });

  const socket = createReconnectingSocket(deps, {
    onOpen: (live) => {
      // A turn that outlived a reconnect is replayed, so the daemon's fresh connection holds it.
      if (speaking) live.send(speakingFrame());
    },
    onMessage: (data) => {
      let json: unknown;
      try {
        json = JSON.parse(data);
      } catch {
        return;
      }
      const event = parseChatEvent(json);
      if (event !== null) callbacks.onEvent(event);
    },
    onPhaseChange: callbacks.onStateChange,
  });

  return {
    reportSpeaking: (value) => {
      if (speaking === value) return;
      speaking = value;
      socket.send(speakingFrame());
    },
    close: socket.close,
  };
}
