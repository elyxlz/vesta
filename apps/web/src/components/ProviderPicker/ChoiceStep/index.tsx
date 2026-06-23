import { FieldDescription } from "@/components/ui/field";
import { PROVIDERS } from "../providers";
import type { ProviderMode } from "../types";

export function ChoiceStep({
  onPick,
}: {
  onPick: (mode: ProviderMode) => void;
}) {
  return (
    <div className="flex w-full flex-col items-start gap-4">
      <div className="flex w-full flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">how should it run?</h2>
        <FieldDescription className="text-center text-[13px]">
          choose how to power your agent.
        </FieldDescription>
      </div>

      <div className="flex w-full gap-2">
        {PROVIDERS.map(({ id, label, tagline, Logo }) => (
          <button
            key={id}
            type="button"
            onClick={() => onPick(id)}
            className="flex flex-1 cursor-pointer flex-col items-start gap-2 rounded-2xl border border-border bg-input/30 p-4 text-left transition-all hover:border-border/80 hover:bg-input/60"
          >
            <Logo className="size-6" />
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold">{label}</span>
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
