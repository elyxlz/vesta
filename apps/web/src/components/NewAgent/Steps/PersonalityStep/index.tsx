import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { FieldDescription } from "@/components/ui/field";
import { Skeleton } from "@/components/ui/skeleton";
import { fetchPersonalities, type Personality } from "@/api/personalities";

export function PersonalityStep({
  onPicked,
}: {
  onPicked: (name: string) => void;
}) {
  const [personalities, setPersonalities] = useState<Personality[] | null>(
    null,
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>("dry");

  useEffect(() => {
    fetchPersonalities()
      .then((list) => setPersonalities(list))
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  return (
    <div className="flex flex-col items-center gap-4 w-[560px] max-w-full px-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">pick a vibe</h2>
        <FieldDescription>
          starting point, not a commitment. ask your agent to change it anytime,
          and it'll keep shifting as it gets to know you.
        </FieldDescription>
      </div>

      {loadError ? (
        <p className="text-xs text-destructive">failed to load: {loadError}</p>
      ) : personalities === null ? (
        <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-2xl" />
          ))}
        </div>
      ) : (
        <div className="grid w-full grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {personalities.map((p) => {
            const isSelected = selected === p.name;
            return (
              <button
                key={p.name}
                onClick={() => setSelected(p.name)}
                className={`group flex h-full flex-col items-center gap-2 rounded-2xl border p-4 text-center transition-all cursor-pointer ${
                  isSelected
                    ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
                    : "border-border bg-input/30 hover:bg-input/60 hover:border-border/80"
                }`}
              >
                <span className="text-3xl leading-none" aria-hidden>
                  {p.emoji}
                </span>
                <span className="text-sm font-semibold">{p.title}</span>
                <span className="text-[11px] leading-snug text-muted-foreground">
                  {p.description}
                </span>
                {p.sample && (
                  <span className="mt-1 text-[11px] italic text-foreground/80">
                    "{p.sample}"
                  </span>
                )}
              </button>
            );
          })}
        </div>
      )}

      <Button
        className="w-full"
        onClick={() => onPicked(selected)}
        disabled={personalities === null && !loadError}
      >
        continue
      </Button>
    </div>
  );
}
