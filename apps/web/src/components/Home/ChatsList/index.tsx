import { useNavigate } from "react-router-dom";
import { MessageSquare, Plus, Users } from "lucide-react";
import { relativeTime, roomKind, roomLabel, type Room } from "@vesta/core";
import { Button } from "@/components/ui/button";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";

// Every conversation on the node, busiest first. A direct room is that agent's own page, so its
// row goes there; every other room has its own route.
function roomRoute(room: Room): string {
  const first = room.agents[0];
  if (roomKind(room) === "direct" && first !== undefined) {
    return `/agent/${encodeURIComponent(first)}/chat`;
  }
  return `/chat/${encodeURIComponent(room.id)}`;
}

function ChatRow({ room }: { room: Room }) {
  const navigate = useNavigate();
  const kind = roomKind(room);
  const Icon = kind === "direct" ? MessageSquare : Users;
  // Only a group is titled by something other than its members, so only a group names them
  // underneath: a direct or peer row would just repeat its own title.
  const subtitle = kind === "group" ? room.agents.join(", ") : null;

  return (
    <li>
      <button
        type="button"
        // Not "open <label>": an agent's own card on the same page already carries that name.
        aria-label={`open ${roomLabel(room)} chat`}
        onClick={() => {
          void navigate(roomRoute(room));
        }}
        className="flex w-full min-w-0 items-center gap-3 rounded-xl bg-muted/50 py-2.5 pr-3 pl-3 text-left transition-colors hover:bg-muted"
      >
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-background text-muted-foreground">
          <Icon className="size-4" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-sm leading-none font-medium">
            {roomLabel(room)}
          </span>
          {subtitle !== null && (
            <span className="truncate text-xs leading-none text-muted-foreground">
              {subtitle}
            </span>
          )}
        </span>
        {room.lastMessageAt !== null && (
          <span className="shrink-0 text-xs text-muted-foreground">
            {relativeTime(room.lastMessageAt)}
          </span>
        )}
      </button>
    </li>
  );
}

export function ChatsList() {
  const { rooms } = useGateway();
  const openDialog = useDialogs((s) => s.setOpen);

  // An ordinary flex item, so the carousel above takes the free space and this list gives way when
  // the window is short; the rows then scroll inside rather than falling off the page.
  return (
    <section className="mx-auto flex w-full max-w-lg min-h-0 flex-col px-4 pb-4">
      <div className="mb-2 flex items-center justify-between px-1">
        <h2 className="text-xs text-muted-foreground">chats</h2>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            openDialog("newRoom", true);
          }}
        >
          <Plus data-icon="inline-start" />
          new group
        </Button>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
        {rooms.map((room) => (
          <ChatRow key={room.id} room={room} />
        ))}
      </ul>
    </section>
  );
}
