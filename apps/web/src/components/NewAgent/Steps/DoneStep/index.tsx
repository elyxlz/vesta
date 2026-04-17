import { useNavigate } from "react-router-dom";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";

export function DoneStep({ agentName }: { agentName: string }) {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col items-center w-[260px] max-w-full px-4">
      <div className="size-10 rounded-full bg-primary/20 flex items-center justify-center">
        <Check size={20} className="text-primary" />
      </div>
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
        continue
      </Button>
    </div>
  );
}
