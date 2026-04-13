import { ProgressBar } from "@/components/ProgressBar";

export function FinalizingStep() {
  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <h2 className="text-base font-semibold">setting up</h2>
      <ProgressBar message="this may take a couple of mins" />
    </div>
  );
}
