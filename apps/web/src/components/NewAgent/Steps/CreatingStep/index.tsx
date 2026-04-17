import { useEffect, useRef, useState } from "react";
import { ProgressBar } from "@/components/ProgressBar";

const MESSAGES = [
  "setting things up...",
  "preparing email &\ncalendar access...",
  "loading browser &\nresearch tools...",
  "setting up reminders & tasks...",
  "almost there...",
];

export function CreatingStep() {
  const [msgIdx, setMsgIdx] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let idx = 0;
    timerRef.current = setInterval(() => {
      idx = Math.min(idx + 1, MESSAGES.length - 1);
      setMsgIdx(idx);
    }, 3000);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return (
    <div className="flex flex-col items-center gap-3 w-[260px] max-w-full px-4">
      <h2 className="text-base font-semibold">setting up</h2>
      <p className="text-xs text-muted-foreground">
        this may take a couple of mins.
      </p>
      <ProgressBar message={MESSAGES[msgIdx]} />
    </div>
  );
}
