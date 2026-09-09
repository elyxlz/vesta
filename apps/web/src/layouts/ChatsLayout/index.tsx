import { Navigate, Outlet, useNavigate, useParams } from "react-router-dom";
import { Home } from "lucide-react";
import { Navbar } from "@/components/Navbar";
import { NewRoomDialog } from "@/components/NewRoomDialog";
import { RoomPane } from "@/components/RoomPane";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useLayout } from "@/stores/use-layout";
import { ConversationList } from "./ConversationList";
import { roomRoute } from "./room-route";

const LIST_WIDTH_CLASS = "w-80";

// The inbox: every conversation on the left, the selected one on the right, the selection in the
// URL. Narrow, the list stands alone and a row opens the full-page chat; the outlet stays mounted
// so a selected room can redirect there.
export function ChatsLayout() {
  const navigate = useNavigate();
  const wide = !useIsMobile();
  const navbarHeight = useLayout((s) => s.navbarHeight);

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
        center={<span className="truncate text-sm font-medium">chats</span>}
        trailing={<StatusPill showHostname={false} />}
      />
      <div className="flex min-h-0 w-full flex-1">
        <aside
          className={cn(
            "flex min-h-0 shrink-0 flex-col pb-4",
            wide ? LIST_WIDTH_CLASS : "w-full",
          )}
          style={{ paddingTop: navbarHeight }}
        >
          <ConversationList wide={wide} />
        </aside>
        <div
          className={cn(
            "relative flex min-h-0 flex-1 flex-col",
            !wide && "hidden",
          )}
        >
          <Outlet />
        </div>
      </div>
      <NewRoomDialog />
    </>
  );
}

export function ChatsIndex() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  return (
    <div
      className="flex flex-1 items-center justify-center text-sm text-muted-foreground"
      style={{ paddingTop: navbarHeight }}
    >
      pick a conversation
    </div>
  );
}

// The selected room. Narrow, the inbox has no pane, so the selection becomes the full-page route
// for that room; a loaded tree that lacks the id sends the inbox back to nothing selected.
export function ChatsRoom() {
  const { roomId } = useParams<{ roomId: string }>();
  const wide = !useIsMobile();
  const { rooms, agentsFetched } = useGateway();
  if (roomId === undefined) return <Navigate to="/chats" replace />;
  if (wide) return <RoomPane roomId={roomId} />;
  const room = rooms.find((candidate) => candidate.id === roomId);
  if (room === undefined) {
    return agentsFetched ? <Navigate to="/chats" replace /> : null;
  }
  return <Navigate to={roomRoute(room, false)} replace />;
}
