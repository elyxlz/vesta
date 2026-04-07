import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";

interface DoneStepProps {
  agentName: string;
  onContinue: () => void;
}

export function DoneStep({ agentName, onContinue }: DoneStepProps) {
  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
      <div className="size-10 rounded-full bg-primary/20 flex items-center justify-center">
        <Check size={20} className="text-primary" />
      </div>
      <h2 className="text-base font-semibold">{agentName} is ready</h2>
      <p className="text-xs text-muted-foreground">say hi.</p>
      <Button className="w-full" onClick={onContinue}>
        continue
      </Button>
    </div>
  );
}
