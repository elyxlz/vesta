import { useCallback, useState } from "react";
import { useResource } from "@vesta/core/react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/Dialog";
import { Spinner } from "@/components/ui/spinner";
import { useGateway } from "@/providers/GatewayProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { filterReleaseNotes, fetchReleaseNotes } from "@vesta/core";
import type { ReleaseNote } from "@vesta/core";
import { useWhatsNewAutoOpen } from "./use-whats-new-auto-open";

function formatReleaseDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function WhatsNewButton() {
  const { reachable } = useGateway();
  const setDialogOpen = useDialogs((s) => s.setOpen);
  const setOpen = useCallback(
    (next: boolean) => {
      setDialogOpen("whatsNew", next);
    },
    [setDialogOpen],
  );

  if (!reachable) return null;

  return (
    <Button
      type="button"
      variant="outline"
      size="lg"
      onClick={() => setOpen(true)}
      className="text-xs"
    >
      <Sparkles data-icon="inline-start" className="size-3.5" />
      What's new
    </Button>
  );
}

// Mounted once at the app root so the post-update auto-open works on any page;
// the settings navbar button opens the same instance via the store.
export function WhatsNewDialog() {
  const { gatewayVersion, gatewayChannel } = useGateway();
  const open = useDialogs((s) => s.open.whatsNew);
  const setDialogOpen = useDialogs((s) => s.setOpen);
  const setOpen = useCallback(
    (next: boolean) => {
      setDialogOpen("whatsNew", next);
    },
    [setDialogOpen],
  );
  // The auto-open already carries the visible notes; a manual open fetches them once per
  // gateway version. fetchReleaseNotes answers null on failure rather than throwing.
  const [autoNotes, setAutoNotes] = useState<ReleaseNote[] | null>(null);
  const handleAutoOpen = useCallback(
    (visible: ReleaseNote[]) => {
      setAutoNotes(visible);
      setOpen(true);
    },
    [setOpen],
  );
  useWhatsNewAutoOpen(handleAutoOpen);

  const fetched = useResource(
    open && autoNotes === null ? gatewayVersion : null,
    () => fetchReleaseNotes(),
  );
  const notes =
    autoNotes ??
    (fetched.data
      ? filterReleaseNotes(fetched.data, {
          version: gatewayVersion,
          channel: gatewayChannel,
        })
      : null);
  const failed = open && !fetched.loading && notes === null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-h-[70vh] gap-5 overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>What's new</DialogTitle>
          <DialogDescription className="sr-only">
            Recent Vesta release notes
          </DialogDescription>
        </DialogHeader>
        {failed ? (
          <p className="text-sm text-muted-foreground">
            Couldn't load release notes
          </p>
        ) : notes === null ? (
          <Spinner className="mx-auto my-2" />
        ) : notes.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Nothing to show yet, check back after the next update.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            {notes.map((entry) => (
              <div key={entry.version} className="flex flex-col gap-1">
                <div className="flex items-baseline gap-2">
                  <span className="text-sm font-semibold">
                    v{entry.version}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatReleaseDate(entry.date)}
                  </span>
                </div>
                <p className="text-sm whitespace-pre-line text-muted-foreground">
                  {entry.message}
                </p>
              </div>
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
