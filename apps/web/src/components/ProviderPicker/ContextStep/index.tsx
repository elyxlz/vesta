import { useState, type ReactNode } from "react";
import type { ContextPreset } from "@/api/agent-defaults";
import { ProviderStep } from "../ProviderStep";

// Presets + the default come from vestad (GET /agent-defaults), passed in by the parent,
// so this step holds no copy of either.
export function ContextStep({
  presets,
  initial,
  onSubmit,
  submitLabel = "continue",
  logo,
  onCancel,
}: {
  presets: ContextPreset[];
  initial: number;
  onSubmit: (tokens: number) => void;
  submitLabel?: string;
  logo?: ReactNode;
  onCancel?: () => void;
}) {
  const [selected, setSelected] = useState<number>(initial);

  return (
    <ProviderStep
      logo={logo}
      title="context window"
      subtitle="how much the agent keeps in context before it compacts. larger holds more at once; smaller is cheaper and compacts sooner."
      submitLabel={submitLabel}
      onSubmit={() => onSubmit(selected)}
      onCancel={onCancel}
    >
      <div className="flex w-full flex-col gap-1.5">
        {presets.map((preset) => (
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
    </ProviderStep>
  );
}
