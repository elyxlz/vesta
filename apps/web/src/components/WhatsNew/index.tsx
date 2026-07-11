import { useCallback, useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useGateway } from "@/providers/GatewayProvider";
import { useWhatsNew } from "@/stores/use-whats-new";
import { filterReleaseNotes, fetchReleaseNotes } from "@/lib/whats-new";
import type { ReleaseNote } from "@/lib/whats-new";
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
  const setOpen = useWhatsNew((s) => s.setOpen);

  if (!reachable) return null;

  return (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      onClick={() => setOpen(true)}
      className="text-muted-foreground"
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
  const open = useWhatsNew((s) => s.open);
  const setOpen = useWhatsNew((s) => s.setOpen);
  const [notes, setNotes] = useState<ReleaseNote[] | null>(null);
  const [failed, setFailed] = useState(false);

  const handleAutoOpen = useCallback(
    (visible: ReleaseNote[]) => {
      setNotes(visible);
      setOpen(true);
    },
    [setOpen],
  );
  useWhatsNewAutoOpen(handleAutoOpen);

  useEffect(() => {
    if (!open || notes !== null) return;
    let cancelled = false;
    void fetchReleaseNotes().then((fetched) => {
      if (cancelled) return;
      setFailed(fetched === null);
      if (fetched === null) return;
      setNotes(
        filterReleaseNotes(fetched, {
          version: gatewayVersion,
          channel: gatewayChannel,
        }),
      );
    });
    return () => {
      cancelled = true;
    };
  }, [open, notes, gatewayVersion, gatewayChannel]);

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
