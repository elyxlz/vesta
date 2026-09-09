import { createContext, useContext } from "react";
import { useRoomSocketState } from "./use-room-socket";

export type RoomSocketValue = ReturnType<typeof useRoomSocketState>;

export const RoomSocketContext = createContext<RoomSocketValue | null>(null);

export function useRoomSocket() {
  const context = useContext(RoomSocketContext);
  if (!context) {
    throw new Error("useRoomSocket must be used within RoomSocketProvider");
  }
  return context;
}
