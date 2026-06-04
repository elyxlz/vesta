import { useNavigate } from "react-router-dom";
import { motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { Orb } from "@/components/Orb";
import { fade } from "@/lib/motion";

export function DoneStep({ agentName }: { agentName: string }) {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center w-[260px] max-w-full px-4">
      <motion.div {...fade}>
        <Orb state="alive" size={96} />
      </motion.div>
      <div className="mt-3 flex flex-col items-center gap-1 text-center">
        <h2 className="text-base font-semibold leading-tight">
          {agentName} is ready
        </h2>
        <p className="text-xs text-muted-foreground">say hi.</p>
      </div>
      <Button
        className="mt-2 w-full"
        onClick={() => navigate(`/agent/${agentName}`)}
      >
        say hi
      </Button>
    </div>
  );
}
