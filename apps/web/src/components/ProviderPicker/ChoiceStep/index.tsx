import type { Manifest } from "@/api/manifest";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { StepHeading } from "@/components/StepHeading";
import { glassHover, glassSurface } from "@/components/NewAgent/glass";
import { PROVIDERS } from "../providers";
import type { ProviderMode } from "../types";

// "compact" is the default settings look; "grid" matches the onboarding vibe
// step: a wide centered grid of glass squircle tiles.
export type ChoiceVariant = "compact" | "grid";

function BackLink({ onBack }: { onBack?: () => void }) {
  if (!onBack) return null;
  return (
    <Button
      type="button"
      variant="link"
      onClick={onBack}
      className="h-auto self-center px-0 py-0 text-xs font-normal text-muted-foreground hover:bg-transparent hover:text-foreground"
    >
      back
    </Button>
  );
}

export function ChoiceStep({
  onPick,
  manifest,
  variant = "compact",
  onBack,
}: {
  onPick: (mode: ProviderMode) => void;
  manifest: Manifest;
  variant?: ChoiceVariant;
  onBack?: () => void;
}) {
  // Ordering and display names are catalog data; only logos + taglines are local presentation.
  const ordered = PROVIDERS.filter(({ id }) => manifest.providers[id]).sort(
    (left, right) =>
      (manifest.providers[left.id]?.order ?? Number.MAX_SAFE_INTEGER) -
      (manifest.providers[right.id]?.order ?? Number.MAX_SAFE_INTEGER),
  );

  if (variant === "grid") {
    return (
      <div className="flex w-[672px] max-w-full flex-col items-center gap-5">
        <StepHeading
          title="how should it run?"
          description="choose how to power your agent."
        />
        <div className="grid w-full grid-cols-1 gap-5 px-4 sm:grid-cols-2 lg:grid-cols-3">
          {ordered.map(({ id, tagline, Logo }) => (
            <button
              key={id}
              type="button"
              onClick={() => onPick(id)}
              className={cn(
                "flex aspect-square cursor-pointer flex-col items-center justify-center gap-1 p-6 text-center",
                glassSurface,
                glassHover,
              )}
            >
              <Logo className="size-7" />
              <span className="text-sm font-semibold">
                {manifest.providers[id]?.display ?? id}
              </span>
              <span className="text-[11px] leading-snug text-muted-foreground">
                {tagline}
              </span>
            </button>
          ))}
        </div>
        <BackLink onBack={onBack} />
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col items-start gap-4">
      <StepHeading
        title="how should it run?"
        description="choose how to power your agent."
      />

      <div className="grid w-full grid-cols-2 gap-2">
        {ordered.map(({ id, tagline, Logo }) => (
          <button
            key={id}
            type="button"
            onClick={() => onPick(id)}
            className="flex flex-1 cursor-pointer flex-col items-start gap-2 rounded-2xl border border-border bg-input/30 p-4 text-left transition-all hover:border-border/80 hover:bg-input/60"
          >
            <Logo className="size-6" />
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold">
                {manifest.providers[id]?.display ?? id}
              </span>
              <span className="text-[11px] leading-snug text-muted-foreground">
                {tagline}
              </span>
            </div>
          </button>
        ))}
      </div>
      <BackLink onBack={onBack} />
    </div>
  );
}
