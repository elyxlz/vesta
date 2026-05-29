import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronLeftIcon } from "lucide-react";
import { fadeSlide } from "@/lib/motion";
import type { OpenRouterConfig } from "@/api/agents";
import { ChoiceStep } from "./ChoiceStep";
import { KeyStep } from "./KeyStep";
import { ModelStep } from "./ModelStep";
import type { ProviderMode } from "./types";

type InternalStep = "choice" | "key" | "model";

export function ProviderPicker({
  onDone,
  onBack,
}: {
  onDone: (config: OpenRouterConfig | null) => void;
  onBack?: () => void;
}) {
  const [step, setStep] = useState<InternalStep>("choice");
  const [key, setKey] = useState("");
  const [zdr, setZdr] = useState(true);
  const [model, setModel] = useState("");

  const handleChoice = (mode: ProviderMode) => {
    if (mode === "claude") {
      onDone(null);
      return;
    }
    setStep("key");
  };

  const handleKeyNext = (newKey: string, newZdr: boolean) => {
    setKey(newKey);
    setZdr(newZdr);
    setStep("model");
  };

  const handleModelSubmit = (newModel: string) => {
    onDone({ key, model: newModel, zdr });
  };

  const back = (() => {
    if (step === "choice") return onBack;
    if (step === "key") return () => setStep("choice");
    return () => setStep("key");
  })();

  return (
    <div className="relative flex w-[380px] max-w-full flex-col items-center gap-4 px-4">
      {back && (
        <button
          type="button"
          onClick={back}
          className="absolute top-0 left-0 -ml-1 flex size-7 items-center justify-center rounded-full text-muted-foreground transition hover:bg-input/60 hover:text-foreground"
          aria-label="back"
        >
          <ChevronLeftIcon className="size-4" />
        </button>
      )}

      <AnimatePresence mode="wait">
        <motion.div key={step} {...fadeSlide} className="w-full">
          {step === "choice" && <ChoiceStep onPick={handleChoice} />}
          {step === "key" && (
            <KeyStep
              initialKey={key}
              initialZdr={zdr}
              onNext={handleKeyNext}
            />
          )}
          {step === "model" && (
            <ModelStep
              initialModel={model}
              onModelChange={setModel}
              onSubmit={handleModelSubmit}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}

export type { ProviderMode };
