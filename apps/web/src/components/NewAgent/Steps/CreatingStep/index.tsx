import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Orb } from "@/components/Orb";
import {
  buildPhaseMessage,
  getBuildPhase,
  type BuildPhase,
} from "@/api/agents";

const BUILD_PHASE_POLL_MS = 1000;

// One screen for the whole birth: the same mounted orb works (busy), dims on a
// failure (off), and wakes up (alive), never remounting between phases.
export function CreatingStep({
  agentName,
  done,
  error,
  onRetry,
}: {
  agentName: string;
  done: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const navigate = useNavigate();
  // Track the latest reported phase so the status line follows the real build
  // and never walks backwards once a phase has been seen.
  const [phase, setPhase] = useState<BuildPhase | null>(null);
  const building = !done && error === null;

  useEffect(() => {
    if (!building) return;
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
  }, [agentName, building]);

  const orbState = error !== null ? "off" : done ? "alive" : "busy";

  return (
    <div className="flex flex-col items-center w-[260px] max-w-full px-4">
      <Orb state={orbState} size={96} />
      <div className="mt-3 flex flex-col items-center gap-1 text-center">
        {done ? (
          <h2 className="text-base font-semibold leading-tight">
            {agentName} is ready
          </h2>
        ) : error !== null ? (
          <p
            role="status"
            aria-live="polite"
            className="text-xs text-destructive"
          >
            setup failed: {error}
          </p>
        ) : (
          <>
            <AnimatePresence mode="wait">
              <motion.p
                key={buildPhaseMessage(phase)}
                role="status"
                aria-live="polite"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="text-xs text-muted-foreground"
              >
                {buildPhaseMessage(phase)}
              </motion.p>
            </AnimatePresence>
            <p className="text-xs text-muted-foreground">
              first setup can take several minutes.
            </p>
          </>
        )}
      </div>
      {done && (
        <Button
          className="mt-2 w-full"
          onClick={() => {
            void navigate(`/agent/${agentName}/chat`);
          }}
        >
          say hi
        </Button>
      )}
      {error !== null && (
        <Button className="mt-2 w-full" onClick={onRetry}>
          try again
        </Button>
      )}
    </div>
  );
}
