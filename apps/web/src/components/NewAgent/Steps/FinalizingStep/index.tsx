import { useEffect } from "react";
import { ProgressBar } from "@/components/ProgressBar";
import { waitForReady } from "@/api";
import { applyPersonality } from "@/api/personalities";

const READY_RETRIES = 9;
const READY_TIMEOUT_SECONDS = 20;

export function FinalizingStep({
  agentName,
  personality,
  onDone,
}: {
  agentName: string;
  personality: string | null;
  onDone: () => void;
}) {
  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      for (let i = 0; i < READY_RETRIES; i++) {
        try {
          await waitForReady(agentName, READY_TIMEOUT_SECONDS);
          break;
        } catch {
          if (i === READY_RETRIES - 1) break;
        }
      }
      if (cancelled) return;

      if (personality && personality !== "default") {
        try {
          await applyPersonality(agentName, personality);
        } catch {
          /* non-fatal: default personality stays active */
        }
      }
      if (!cancelled) onDone();
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [agentName, personality, onDone]);

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <h2 className="text-base font-semibold">setting up</h2>
      <ProgressBar message="this may take a couple of mins" />
    </div>
  );
}
