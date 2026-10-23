import { motion as m } from "motion/react";
import { wakeWordBehavior } from "@vesta/core";
import { Switch } from "@/components/ui/switch";
import { sheetEase } from "@/lib/motion";
import { useVoice } from "@/stores/use-voice";

// The wake word of this app, in the panel's top right corner: on, a conversation waits for the
// phrase. Absent for a voice service with no wake word.
export function WakeWordSwitch() {
  const behaviors = useVoice((s) => s.behaviors);
  const toggleWakeWord = useVoice((s) => s.toggleWakeWord);
  const wake = wakeWordBehavior(behaviors?.settings);
  if (!wake) return null;
  return (
    <m.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.19, ease: sheetEase } }}
      transition={{ delay: 0.12, duration: 0.38, ease: sheetEase }}
      className="absolute top-3 right-4 z-10"
    >
      <label className="flex cursor-pointer items-center gap-2 rounded-full bg-muted py-1.5 pr-2 pl-3 text-xs text-muted-foreground select-none">
        wake word
        <Switch size="sm" checked={wake.on} onCheckedChange={toggleWakeWord} />
      </label>
    </m.div>
  );
}
