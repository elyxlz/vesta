import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Manifest } from "@/api/manifest";
import { glassHover, glassSelected, glassSurface } from "../../glass";

export function PersonalityStep({
  personalities,
  selected,
  onPick,
}: {
  personalities: Manifest["personalities"] | null;
  selected: string;
  onPick: (name: string) => void;
}) {
  if (personalities === null) {
    return (
      <div className="grid w-full grid-cols-1 gap-6 px-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton
            key={i}
            className="h-40 w-full rounded-3xl [corner-shape:squircle]"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="grid w-full grid-cols-1 gap-6 px-4 sm:grid-cols-2 lg:grid-cols-3">
      {personalities.map((p) => {
        const isSelected = selected === p.name;
        return (
          <button
            key={p.name}
            onClick={() => {
              onPick(p.name);
            }}
            aria-pressed={isSelected}
            className={cn(
              "flex h-full cursor-pointer flex-col items-center gap-2 p-6 text-center",
              glassSurface,
              glassHover,
              isSelected && glassSelected,
            )}
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
  );
}
