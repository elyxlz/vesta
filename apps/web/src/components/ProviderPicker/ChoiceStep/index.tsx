import type { Manifest } from "@/api/manifest";
import { StepHeading } from "@/components/StepHeading";
import { PROVIDERS } from "../providers";
import type { ProviderMode } from "../types";

export function ChoiceStep({
  onPick,
  manifest,
}: {
  onPick: (mode: ProviderMode) => void;
  manifest: Manifest;
}) {
  // Ordering and display names are catalog data; only logos + taglines are local presentation.
  const ordered = PROVIDERS.filter(({ id }) => manifest.providers[id]).sort(
    (left, right) =>
      (manifest.providers[left.id]?.order ?? Number.MAX_SAFE_INTEGER) -
      (manifest.providers[right.id]?.order ?? Number.MAX_SAFE_INTEGER),
  );
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
    </div>
  );
}
