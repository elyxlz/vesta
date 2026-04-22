import { useEffect, useState } from "react";
import { Check, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldLabel,
} from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import {
  applyPersonality,
  fetchPersonalities,
  type Personality,
} from "@/api/personalities";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

type Status =
  | { kind: "idle" }
  | { kind: "applying" }
  | { kind: "error"; message: string };

export function PersonalityCard() {
  const { name: agentName, agent, restart } = useSelectedAgent();
  const isAlive = agent?.status === "alive";

  const [personalities, setPersonalities] = useState<Personality[] | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  useEffect(() => {
    if (!agentName || !isAlive) return;
    setPersonalities(null);
    setLoadError(null);
    setStatus({ kind: "idle" });
    fetchPersonalities(agentName)
      .then((list) => {
        setPersonalities(list);
        setSelected(list.find((p) => p.active)?.name ?? null);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [agentName, isAlive]);

  const active = personalities?.find((p) => p.active) ?? null;
  const dirty = selected !== null && selected !== (active?.name ?? null);

  const onSave = async () => {
    if (!agentName || !selected || !dirty) return;
    setStatus({ kind: "applying" });
    try {
      await applyPersonality(agentName, selected);
      restart();
    } catch (e) {
      setStatus({ kind: "error", message: (e as Error).message });
    }
  };

  return (
    <Card size="sm">
      <CardContent>
        <Field orientation="vertical" className="gap-3">
          <Field
            orientation="horizontal"
            className="items-start justify-between"
          >
            <FieldContent>
              <FieldLabel className="flex items-center gap-2">
                <RotateCcw className="size-4 text-muted-foreground" />
                reset personality
              </FieldLabel>
              <FieldDescription>
                overwrites the personality block in memory. anything the nightly
                dreamer has shaped will be replaced.
              </FieldDescription>
            </FieldContent>
          </Field>

          {!isAlive ? (
            <p className="text-xs text-muted-foreground">
              agent must be running
            </p>
          ) : loadError ? (
            <p className="text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : personalities === null ? (
            <div className="flex flex-col gap-2">
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
              <Skeleton className="h-12 w-full rounded-xl" />
            </div>
          ) : (
            <>
              <p className="text-[11px] text-muted-foreground">
                current:{" "}
                {active ? (
                  <span className="text-foreground">
                    {active.emoji && (
                      <span className="mr-1" aria-hidden>
                        {active.emoji}
                      </span>
                    )}
                    {active.title}
                  </span>
                ) : (
                  <span className="italic">custom (no preset match)</span>
                )}
              </p>

              <div className="flex flex-col gap-2">
                {personalities.map((p) => {
                  const isSelected = selected === p.name;
                  return (
                    <button
                      key={p.name}
                      onClick={() => setSelected(p.name)}
                      disabled={status.kind === "applying"}
                      className={`group flex items-start gap-3 rounded-xl border p-3 text-left transition-colors cursor-pointer disabled:cursor-not-allowed ${
                        isSelected
                          ? "border-primary/60 bg-primary/5 ring-1 ring-primary/30"
                          : "border-transparent bg-input/30 hover:bg-input/60"
                      }`}
                    >
                      <div
                        className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border ${
                          isSelected
                            ? "border-primary bg-primary text-primary-foreground"
                            : "border-muted-foreground/30"
                        }`}
                      >
                        {isSelected && <Check className="size-3" />}
                      </div>
                      <div className="flex min-w-0 flex-col gap-0.5">
                        <span className="text-sm font-medium">
                          {p.emoji && (
                            <span className="mr-1.5" aria-hidden>
                              {p.emoji}
                            </span>
                          )}
                          {p.title}
                        </span>
                        {p.description && (
                          <span className="text-xs text-muted-foreground">
                            {p.description}
                          </span>
                        )}
                      </div>
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center justify-between gap-3">
                <span
                  className={`text-[10px] ${
                    status.kind === "error" || dirty
                      ? "text-destructive"
                      : "text-muted-foreground/60"
                  }`}
                >
                  {status.kind === "error"
                    ? status.message
                    : status.kind === "applying"
                      ? "applying, agent will restart"
                      : dirty
                        ? "save will overwrite the current personality and restart the agent"
                        : ""}
                </span>
                <Button
                  size="sm"
                  disabled={!dirty || status.kind === "applying"}
                  onClick={onSave}
                >
                  save and restart
                </Button>
              </div>
            </>
          )}
        </Field>
      </CardContent>
    </Card>
  );
}
