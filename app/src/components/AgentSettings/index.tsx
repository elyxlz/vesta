import { ActionsCard } from "./ActionsCard";
import { KeybindsCard } from "./KeybindsSection";
import { PlanUsage } from "./PlanUsage";
import { SttCard, TtsCard } from "./VoiceSection";

export function AgentSettings() {
  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-y-auto pt-2">
      <div className="py-6 flex items-center justify-center min-h-11">
        <h1 className="text-lg font-semibold">agent settings</h1>
      </div>

      <div className="grid w-full max-w-5xl mx-auto gap-4 pb-6 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
        <div className="flex flex-col gap-4 lg:sticky lg:top-6">
          <ActionsCard />
          <KeybindsCard />
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          <PlanUsage />
          <SttCard />
          <TtsCard />
        </div>
      </div>
    </div>
  );
}
