import { useEffect, type ReactNode } from "react";
import { isEditableTarget } from "@/lib/dom";
import { useVoice } from "@/stores/use-voice";
import { useVoiceActivation } from "@/stores/use-voice-activation";
import { useTheme } from "@/providers/ThemeProvider";

export function KeybindProvider({ children }: { children: ReactNode }) {
  const { cycleTheme } = useTheme();
  const activation = useVoiceActivation((s) => s.mode);

  useEffect(() => {
    // Space is the keyboard twin of the mic: it starts a dictation and confirms it, on
    // release (hold) or on the next press (toggle).
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;

      if (event.key === " ") {
        const { sttAvailable, recordingMode, startVoice, stopVoice } =
          useVoice.getState();
        if (!sttAvailable) return;
        event.preventDefault();
        if (recordingMode === null) startVoice("dictation");
        else if (recordingMode === "dictation" && activation === "toggle")
          stopVoice();
        return;
      }

      if (event.key.toLowerCase() === "d") {
        cycleTheme();
        return;
      }
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key !== " " || activation !== "hold") return;
      const { recordingMode, stopVoice } = useVoice.getState();
      if (recordingMode === "dictation") stopVoice();
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [cycleTheme, activation]);

  return <>{children}</>;
}
