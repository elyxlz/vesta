import type { ReactNode } from "react";
import { useRoomSocketState } from "./use-room-socket";
import { useRoom } from "@/providers/RoomProvider/context";
import { useNotifications } from "@/providers/NotificationProvider/context";
import { useVoice } from "@/stores/use-voice";
import { RoomSocketContext } from "./context";

// The live conversation of the room above it. The socket opens as soon as the room exists,
// whatever its agents are doing, so history loads even for an agent that is not signed in yet
// (the composer stays disabled until sign-in). Speech is a direct-room feature: the voice
// services belong to one agent.
export function RoomSocketProvider({ children }: { children: ReactNode }) {
  const { roomId, kind, label, directAgent } = useRoom();
  const { speak, prefetch } = useVoice();
  const { notifyAssistant } = useNotifications();
  const direct = kind === "direct";

  const socket = useRoomSocketState({
    roomId,
    pacingAgent: directAgent?.name ?? null,
    onAssistantMessage: (text) => {
      if (direct) speak(text);
      notifyAssistant(label, text, roomId);
    },
    onPrefetch: direct ? prefetch : undefined,
  });

  return (
    <RoomSocketContext.Provider value={socket}>
      {children}
    </RoomSocketContext.Provider>
  );
}
