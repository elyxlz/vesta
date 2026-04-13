import { useEffect, useState, type ReactNode } from "react";
import { isEditableTarget } from "@/lib/dom";
import { useVoice } from "@/stores/use-voice";
import { useTheme } from "@/providers/ThemeProvider";

export type SpacebarMode = "toggle" | "hold";
const STORAGE_KEY = "spacebar-mode";

function getStoredMode(): SpacebarMode {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "hold") return "hold";
  return "toggle";
}

export function useSpacebarMode() {
  const [mode, setModeState] = useState<SpacebarMode>(getStoredMode);

  const setMode = (next: SpacebarMode) => {
    localStorage.setItem(STORAGE_KEY, next);
    setModeState(next);
  };

  return [mode, setMode] as const;
}

export function KeybindProvider({ children }: { children: ReactNode }) {
  const { cycleTheme } = useTheme();
  const [spacebarMode] = useSpacebarMode();

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
          // Hold mode: start recording on keydown
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
