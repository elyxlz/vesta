import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StepHeading } from "@/components/StepHeading";
import { useManifest } from "@/hooks/use-manifest";

export function PersonalityStep({
  onPicked,
}: {
  onPicked: (name: string) => void;
}) {
  // The personality catalog + the default come from the manifest (GET /manifest), not a side endpoint
  // or a hardcoded copy. Until the user picks, fall through to the manifest default once it loads.
  const manifest = useManifest();
  const [picked, setPicked] = useState<string | null>(null);
  const selected = picked ?? manifest?.default_personality ?? "";
  const personalities = manifest?.personalities ?? null;

  return (
    <div className="flex flex-col items-center gap-4 w-[560px] max-w-full px-4">
      <StepHeading
        title="pick a vibe"
        description="starting point, not a commitment. ask your agent to change it anytime, and it'll keep shifting as they get to know you."
      />

      {personalities === null ? (
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
                onClick={() => setPicked(p.name)}
                aria-pressed={isSelected}
                className={`group flex h-full flex-col items-center gap-2 rounded-2xl border p-4 text-center transition-all cursor-pointer ${
                  isSelected
                    ? "border-primary bg-primary/10"
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
        disabled={personalities === null || !selected}
      >
        continue
      </Button>
    </div>
  );
}
