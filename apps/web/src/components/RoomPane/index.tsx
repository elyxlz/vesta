import type { ReactNode } from "react";
import { Chat } from "@/components/Chat";
import { RoomProvider } from "@/providers/RoomProvider";
import { RoomSocketProvider } from "@/providers/RoomSocketProvider";

// One conversation's providers and its full-height transcript. Children mount inside the
// providers, so a navbar rendered here can read the room; the inbox passes none.
export function RoomPane({
  roomId,
  children,
}: {
  roomId: string;
  children?: ReactNode;
}) {
  return (
    <RoomProvider roomId={roomId}>
      <RoomSocketProvider>
        {children}
        <div className="relative flex min-h-0 flex-1 flex-col">
          <div className="absolute inset-0 flex flex-col">
            <Chat fullscreen />
          </div>
        </div>
      </RoomSocketProvider>
    </RoomProvider>
  );
}
