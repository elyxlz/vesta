import { NavLink } from "react-router-dom";
import { Plus } from "lucide-react";
import {
  directRoomAgent,
  relativeTime,
  roomLabel,
  type OrbVisualState,
  type Room,
} from "@vesta/core";
import { useAgentVisualStatus } from "@vesta/core/react";
import { Orb } from "@/components/Orb";
import { Button } from "@/components/ui/button";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { roomRoute } from "./room-route";

const DIRECT_ORB_SIZE = 44;
const MEMBER_ORB_SIZE = 30;
const CLUSTER_MAX = 3;

// An agent's orb and status word as the roster reports them; a name the roster lacks renders off.
function useMemberStatus(name: string | null) {
  const { agents } = useGateway();
  const agent =
    name === null ? null : (agents.find((row) => row.name === name) ?? null);
  return useAgentVisualStatus(
    useOptionalController(),
    agent,
    agent?.activityState ?? "idle",
  );
}

function StatusOrb({
  orbState,
  size,
}: {
  orbState: OrbVisualState;
  size: number;
}) {
  return <Orb state={orbState} size={size} glow={0.4} suppressMotion />;
}

function MemberOrb({ name, size }: { name: string; size: number }) {
  const { orbState } = useMemberStatus(name);
  return <StatusOrb orbState={orbState} size={size} />;
}

function ChatRow({ room }: { room: Room }) {
  const wide = !useIsMobile();
  const label = roomLabel(room);
  const agent = directRoomAgent(room);
  const status = useMemberStatus(agent);

  // Striped like the backups list, so neighboring rows read apart; the selected row takes a
  // tint twice the stripe's, so it stands out on either parity.
  return (
    <li className="rounded-md odd:bg-foreground/[0.07]">
      <NavLink
        to={roomRoute(room, wide)}
        end
        aria-label={`open ${label} chat`}
        className={({ isActive }) =>
          cn(
            "flex w-full min-w-0 items-center gap-3 rounded-md py-2 pr-3 pl-2 text-left transition-colors hover:bg-foreground/[0.1]",
            isActive && wide && "bg-foreground/[0.14]",
          )
        }
      >
        {agent !== null ? (
          <StatusOrb orbState={status.orbState} size={DIRECT_ORB_SIZE} />
        ) : (
          <span className="flex shrink-0 -space-x-2">
            {room.agents.slice(0, CLUSTER_MAX).map((name) => (
              <MemberOrb key={name} name={name} size={MEMBER_ORB_SIZE} />
            ))}
          </span>
        )}
        <span className="flex min-w-0 flex-1 flex-col gap-1">
          <span className="truncate text-sm leading-none font-medium">
            {label}
          </span>
          <span className="truncate text-xs leading-none text-muted-foreground">
            {agent !== null ? status.label : room.agents.join(", ")}
          </span>
        </span>
        {room.lastMessageAt !== null && (
          <span className="shrink-0 text-xs text-muted-foreground">
            {relativeTime(room.lastMessageAt)}
          </span>
        )}
      </NavLink>
    </li>
  );
}

// Every conversation on the node, busiest first, with the way to start a group in the header so a
// long list never scrolls it away.
export function ConversationList() {
  const { rooms } = useGateway();
  const openDialog = useDialogs((s) => s.setOpen);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-2 flex items-center justify-between px-3">
        <h2 className="text-xs text-muted-foreground">chats</h2>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="new group"
          onClick={() => {
            openDialog("newRoom", true);
          }}
        >
          <Plus />
        </Button>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2">
        {rooms.map((room) => (
          <ChatRow key={room.id} room={room} />
        ))}
      </ul>
    </div>
  );
}
