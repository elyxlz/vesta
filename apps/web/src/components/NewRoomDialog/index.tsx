import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createRoom } from "@vesta/core";
import { httpClient } from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/utils";
import { useOptionalController } from "@/providers/ControllerProvider/context";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { useToast } from "@/stores/use-toast";
import { waitForRoom } from "./wait-for-room";

// Opening a group: a name and the agents that answer in it. The node returns the room, and the
// conversation opens on its own route once the room list on /sync carries it.
function NewRoomBody({ onClose }: { onClose: () => void }) {
  const { agents } = useGateway();
  const controller = useOptionalController();
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const canCreate = name.trim().length > 0 && members.length > 0 && !creating;

  const toggle = (agent: string) => {
    setMembers((current) =>
      current.includes(agent)
        ? current.filter((member) => member !== agent)
        : [...current, agent],
    );
  };

  const create = async () => {
    setCreating(true);
    try {
      const opened = await createRoom(httpClient, name.trim(), members);
      // The room route reads the tree, so hold the dialog until the delta lands.
      if (controller) await waitForRoom(controller.replica, opened.room.id);
      onClose();
      await navigate(`/chat/${encodeURIComponent(opened.room.id)}`);
    } catch (error) {
      toast.error(errorMessage(error, "could not open the group"));
      setCreating(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>new group</DialogTitle>
        <DialogDescription>
          a conversation the agents you pick all read and answer in.
        </DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-4">
        <Input
          autoFocus
          value={name}
          placeholder="group name"
          aria-label="group name"
          onChange={(event) => {
            setName(event.target.value);
          }}
        />
        <ul className="flex flex-col gap-1">
          {agents.map((agent) => (
            <li key={agent.name}>
              <Label className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 hover:bg-muted/60">
                <Checkbox
                  checked={members.includes(agent.name)}
                  onCheckedChange={() => {
                    toggle(agent.name);
                  }}
                />
                <span className="truncate text-sm">{agent.name}</span>
              </Label>
            </li>
          ))}
        </ul>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          cancel
        </Button>
        <Button
          disabled={!canCreate}
          onClick={() => {
            void create();
          }}
        >
          create
        </Button>
      </DialogFooter>
    </>
  );
}

export function NewRoomDialog() {
  const open = useDialogs((s) => s.open.newRoom);
  const setDialogOpen = useDialogs((s) => s.setOpen);
  const setOpen = (next: boolean) => {
    setDialogOpen("newRoom", next);
  };
  return (
    <Dialog drawerOnMobile open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[min(60vh,480px)] sm:max-w-md">
        {open && (
          <NewRoomBody
            onClose={() => {
              setOpen(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
