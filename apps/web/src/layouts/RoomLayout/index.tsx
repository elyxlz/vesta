import { Navigate, useNavigate, useParams } from "react-router-dom";
import { Home } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { RoomPane } from "@/components/RoomPane";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useRoom } from "@/providers/RoomProvider/context";

// A conversation that is not one agent's own page: its whole screen is the chat, titled by the
// room and led by the way back to Home. The agent page keeps its own navbar and panes.
export function RoomLayout() {
  const { roomId } = useParams<{ roomId: string }>();
  if (roomId === undefined) return <Navigate to="/" replace />;

  return (
    <RoomPane roomId={roomId}>
      <RoomNavbar />
    </RoomPane>
  );
}

function RoomNavbar() {
  const { label } = useRoom();
  const navigate = useNavigate();

  return (
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
  );
}
