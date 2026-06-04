import { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Field, FieldContent, FieldLabel } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { fetchConstitution, saveConstitution } from "@/api/constitution";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

type Status =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved" }
  | { kind: "error"; message: string };

// The constitution is host-side config (not stored in the container), so it loads and
// saves regardless of whether the agent is running. Saving restarts the agent so the new
// charter is loaded into its system prompt. The agent itself cannot edit it.
export function ConstitutionCard() {
  const { name: agentName, restart } = useSelectedAgent();

  const [original, setOriginal] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>({ kind: "idle" });

  useEffect(() => {
    if (!agentName) return;
    setOriginal(null);
    setLoadError(null);
    fetchConstitution(agentName)
      .then((content) => {
        setOriginal(content);
        setValue(content);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, [agentName]);

  const dirty = original !== null && value !== original;

  const onSave = async () => {
    if (!agentName || !dirty) return;
    setStatus({ kind: "saving" });
    try {
      await saveConstitution(agentName, value);
      setOriginal(value);
      setStatus({ kind: "saved" });
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
            className="items-center justify-between"
          >
            <FieldContent>
              <FieldLabel className="flex items-center gap-2">
                <ScrollText className="size-4 text-muted-foreground" />
                constitution
              </FieldLabel>
            </FieldContent>
          </Field>

          <p className="text-xs text-muted-foreground">
            a charter prepended to the agent's memory. the agent cannot edit it.
          </p>

          {loadError ? (
            <p className="text-xs text-destructive">
              failed to load: {loadError}
            </p>
          ) : original === null ? (
            <Skeleton className="h-64 w-full rounded-2xl" />
          ) : (
            <>
              <Textarea
                value={value}
                onChange={(e) => setValue(e.target.value)}
                spellCheck={false}
                placeholder="empty — set principles, boundaries, or facts the agent must always honor"
                className="min-h-64 max-h-[60vh] overflow-auto font-mono text-xs"
              />
              <div className="flex items-center justify-between">
                <span
                  className={`text-[10px] ${
                    status.kind === "error" || (status.kind === "idle" && dirty)
                      ? "text-destructive"
                      : "text-muted-foreground/60"
                  }`}
                >
                  {status.kind === "saving"
                    ? "saving..."
                    : status.kind === "saved"
                      ? "saved, restarting agent"
                      : status.kind === "error"
                        ? status.message
                        : dirty
                          ? "unsaved changes — save will restart the agent"
                          : ""}
                </span>
                <Button
                  size="sm"
                  disabled={!dirty || status.kind === "saving"}
                  onClick={onSave}
                >
                  save
                </Button>
              </div>
            </>
          )}
        </Field>
      </CardContent>
    </Card>
  );
}
