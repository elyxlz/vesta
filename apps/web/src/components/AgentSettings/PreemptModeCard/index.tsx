import { useEffect, useState } from "react";
import { MessageSquareDot, Zap } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { getPreemptMode, setPreemptMode, type PreemptMode } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useRestartPending } from "@/stores/use-restart-pending";
import { errorMessage } from "@/lib/utils";

const MODE_HINT: Record<PreemptMode, string> = {
  message:
    "Background work keeps running when an urgent message cuts in; a tool call already running finishes first.",
  interrupt:
    "Urgent messages cut in immediately, even mid-tool, but running background agents are stopped.",
};

// How an interrupting notification preempts a running turn. A pref: saved on change, applies on
// the agent's next restart (flagged via the shared restart-pending store, offered in the navbar).
export function PreemptModeCard() {
  const { name: agentName } = useSelectedAgent();
  const markRestartPending = useRestartPending((s) => s.markPending);
  const [mode, setMode] = useState<PreemptMode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!agentName) return;
    let ignore = false;
    setMode(null);
    setError(null);
    getPreemptMode(agentName)
      .then((m) => {
        if (!ignore) setMode(m);
      })
      .catch((e: unknown) => {
        if (!ignore) setError(errorMessage(e, "failed to load preempt mode"));
      });
    return () => {
      ignore = true;
    };
  }, [agentName]);

  const select = (next: PreemptMode) => {
    if (!agentName || !mode || next === mode) return;
    const previous = mode;
    setMode(next);
    setError(null);
    setPreemptMode(agentName, next)
      .then(() => markRestartPending(agentName))
      .catch((e: unknown) => {
        setMode(previous);
        setError(errorMessage(e, "failed to update preempt mode"));
      });
  };

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Urgent message handling</CardTitle>
        <CardDescription>
          How an interrupting message cuts into work already in progress.
          Applies after a restart.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {mode === null && !error ? (
          <Skeleton className="h-9 w-full" />
        ) : (
          <ToggleGroup
            type="single"
            value={mode ?? undefined}
            onValueChange={(value) => {
              if (value) select(value as PreemptMode);
            }}
            variant="outline"
            spacing={2}
          >
            <ToggleGroupItem value="message">
              <MessageSquareDot /> Graceful
            </ToggleGroupItem>
            <ToggleGroupItem value="interrupt">
              <Zap /> Immediate
            </ToggleGroupItem>
          </ToggleGroup>
        )}
        {mode !== null && (
          <p className="text-muted-foreground text-xs">{MODE_HINT[mode]}</p>
        )}
        {error && <p className="text-destructive text-xs">{error}</p>}
      </CardContent>
    </Card>
  );
}
