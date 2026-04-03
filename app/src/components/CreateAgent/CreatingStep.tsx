import { ProgressBar } from "@/components/ProgressBar";
import { CREATING_MESSAGES } from "./types";

interface CreatingStepProps {
  messageIndex: number;
}

export function CreatingStep({ messageIndex }: CreatingStepProps) {
  return (
    <div className="flex flex-col items-center gap-4 w-full max-w-[260px] px-4">
      <h2 className="text-base font-semibold">setting up</h2>
      <p className="text-xs text-muted-foreground">
        this may take a couple of mins.
      </p>
      <ProgressBar message={CREATING_MESSAGES[messageIndex]} />
    </div>
  );
}
