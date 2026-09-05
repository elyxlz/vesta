import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Home } from "lucide-react";
import { Chat } from "@/components/Chat";
import { Navbar } from "@/components/Navbar";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { RoomProvider } from "@/providers/RoomProvider";
import { useRoom } from "@/providers/RoomProvider/context";
import { RoomSocketProvider } from "@/providers/RoomSocketProvider";

// A conversation that is not one agent's own page: its whole screen is the chat, titled by the
// room and led by the way back to Home. The agent page keeps its own navbar and panes.
export function RoomLayout() {
  const { roomId } = useParams<{ roomId: string }>();
  if (roomId === undefined) return <Navigate to="/" replace />;

  return (
    <RoomProvider roomId={roomId}>
      <RoomSocketProvider>
        <RoomScreen />
      </RoomSocketProvider>
    </RoomProvider>
  );
}

function RoomScreen() {
  const { label } = useRoom();
  const navigate = useNavigate();

  return (
    <>
      <Navbar
        leading={
          <Button
            variant="outline"
            size="icon-lg"
            aria-label="home"
            onClick={() => {
              void navigate("/");
            }}
          >
            <Home />
          </Button>
        }
        center={<span className="truncate text-sm font-medium">{label}</span>}
        trailing={<StatusPill showHostname={false} />}
      />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div className="absolute inset-0 flex flex-col">
          <Chat fullscreen />
        </div>
      </div>
    </>
  );
}
