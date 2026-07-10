import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Orb } from "@/components/Orb";
import { StepHeading } from "@/components/StepHeading";
import { fade } from "@/lib/motion";

export function DoneStep({ agentName }: { agentName: string }) {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <motion.div {...fade}>
        <Orb state="alive" size={96} />
      </motion.div>
      <StepHeading title={`${agentName} is ready`} />
      <Button
        className="w-full"
        onClick={() => navigate(`/agent/${agentName}`)}
      >
        say hi
      </Button>
    </div>
  );
}
