import { useEffect, useState } from "react";
import { ProgressBar } from "@/components/ProgressBar";
import { StepHeading } from "@/components/StepHeading";
import {
  buildPhaseMessage,
  getBuildPhase,
  type BuildPhase,
} from "@/api/agents";

const BUILD_PHASE_POLL_MS = 1000;

export function CreatingStep({ agentName }: { agentName: string }) {
  // Track the latest reported phase so the status line follows the real build
  // and never walks backwards once a phase has been seen. The indeterminate bar
  // stays honest about not knowing the remaining time.
  const [phase, setPhase] = useState<BuildPhase | null>(null);

  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const next = await getBuildPhase(agentName);
        if (active && next !== null) setPhase(next);
      } catch {
        // best-effort status only; the create flow owns success and failure.
      }
    };
    void poll();
    const id = setInterval(() => void poll(), BUILD_PHASE_POLL_MS);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, [agentName]);

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <StepHeading
        title="setting up"
        description="first setup can take several minutes."
      />
      <ProgressBar message={buildPhaseMessage(phase)} />
    </div>
  );
}
