import { useState } from "react";
import { Button } from "@/components/ui/button";
import { FieldDescription } from "@/components/ui/field";

interface ContextPreset {
  tokens: number;
  label: string;
  note: string;
}

/// Context-window presets. 1M is the default (largest); smaller windows compact
/// sooner and make prompt-cache reads cheaper.
const CONTEXT_PRESETS: ContextPreset[] = [
  { tokens: 1_000_000, label: "1M", note: "most context (default)" },
  { tokens: 500_000, label: "500K", note: "balanced" },
  { tokens: 200_000, label: "200K", note: "cheapest, compacts soonest" },
];

export function ContextStep({
  initial,
  onSubmit,
  submitLabel = "continue",
}: {
  initial?: number;
  onSubmit: (tokens: number) => void;
  submitLabel?: string;
}) {
  const [selected, setSelected] = useState<number>(
    initial ?? CONTEXT_PRESETS[0].tokens,
  );

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(selected);
      }}
      className="flex w-full flex-col items-center gap-4"
    >
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold">context window</h2>
        <FieldDescription>
          how much the agent keeps in context before it compacts. larger holds
          more at once; smaller is cheaper and compacts sooner.
        </FieldDescription>
      </div>

      <div className="flex w-full flex-col gap-1.5">
        {CONTEXT_PRESETS.map((preset) => (
          <button
            key={preset.tokens}
            type="button"
            onClick={() => setSelected(preset.tokens)}
            className={`flex items-center justify-between rounded-xl border p-3 text-left transition-all cursor-pointer ${
              preset.tokens === selected
                ? "border-primary/60 bg-primary/5 ring-2 ring-primary/30"
                : "border-border bg-input/30 hover:bg-input/60 hover:border-border/80"
            }`}
          >
            <span className="text-sm font-medium">{preset.label}</span>
            <span className="text-[11px] text-muted-foreground">
              {preset.note}
            </span>
          </button>
        ))}
      </div>

      <Button type="submit" className="w-full">
        {submitLabel}
      </Button>
    </form>
  );
}
