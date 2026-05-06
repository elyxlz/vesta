import { useEffect, type ReactNode } from "react";
import { isEditableTarget } from "@/lib/dom";
import { useVoice } from "@/stores/use-voice";
import { useVoiceActivation } from "@/stores/use-voice-activation";
import { useTheme } from "@/providers/ThemeProvider";

export function KeybindProvider({ children }: { children: ReactNode }) {
  const { cycleTheme } = useTheme();
  const spacebarMode = useVoiceActivation((s) => s.mode);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;

      if (event.key === " ") {
        const { sttAvailable, toggleVoice } = useVoice.getState();
        if (!sttAvailable) return;
        event.preventDefault();
        if (spacebarMode === "hold") {
          if (!useVoice.getState().isRecording) {
            toggleVoice();
          }
        } else {
          toggleVoice();
        }
        return;
      }

      if (event.key.toLowerCase() === "d") {
        cycleTheme();
        return;
      }
    };

    const handleKeyUp = (event: KeyboardEvent) => {
      if (event.key !== " ") return;
      if (spacebarMode !== "hold") return;
      if (isEditableTarget(event.target)) return;

      const { isRecording, toggleVoice } = useVoice.getState();
      if (isRecording) {
        toggleVoice();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [cycleTheme, spacebarMode]);

  return <>{children}</>;
}
