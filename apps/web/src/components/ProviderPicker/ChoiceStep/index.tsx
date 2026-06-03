import { FieldDescription } from "@/components/ui/field";
import type { ProviderMode } from "../types";

export function ChoiceStep({
  onPick,
}: {
  onPick: (mode: ProviderMode) => void;
}) {
  const cardClass =
    "flex flex-1 flex-col items-center gap-1 rounded-2xl border border-border bg-input/30 p-4 text-center transition-all cursor-pointer hover:bg-input/60 hover:border-border/80";

  return (
    <div className="flex w-full flex-col items-center gap-4">
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">how should it run?</h2>
        <FieldDescription>
          use your Claude account, or bring an OpenRouter API key.
        </FieldDescription>
      </div>

      <div className="flex w-full gap-2">
        <button
          type="button"
          className={cardClass}
          onClick={() => onPick("claude")}
        >
          <span className="text-sm font-semibold">Claude account</span>
          <span className="text-[11px] leading-snug text-muted-foreground">
            sign in with Claude (OAuth)
          </span>
        </button>
        <button
          type="button"
          className={cardClass}
          onClick={() => onPick("openrouter")}
        >
          <span className="text-sm font-semibold">OpenRouter key</span>
          <span className="text-[11px] leading-snug text-muted-foreground">
            pay per token via OpenRouter
          </span>
        </button>
      </div>
    </div>
  );
}
