import { useEffect, type ReactNode } from "react";
import { isEditableTarget } from "@/lib/dom";
import { useVoice } from "@/stores/use-voice";
import { useTheme } from "@/providers/ThemeProvider";

export function KeybindProvider({ children }: { children: ReactNode }) {
  const { cycleTheme } = useTheme();

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;

      if (event.key === " ") {
        const { sttAvailable, toggleVoice } = useVoice.getState();
        if (!sttAvailable) return;
        event.preventDefault();
        toggleVoice();
        return;
      }

      if (event.key.toLowerCase() === "d") {
        cycleTheme();
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [cycleTheme]);

  return <>{children}</>;
}
