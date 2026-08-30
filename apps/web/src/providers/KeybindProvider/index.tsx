import { useEffect, type ReactNode } from "react";
import { isEditableTarget } from "@/lib/dom";
import { useVoice } from "@/stores/use-voice";
import { useVoiceActivation } from "@/stores/use-voice-activation";
import { useTheme } from "@/providers/ThemeProvider";

function isButtonTarget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest("button") !== null;
}

// The chat composer textarea, when the event is on it; null for any other target. Marked so
// Space can dictate from an empty composer without also firing in unrelated inputs.
function composerTextarea(
  target: EventTarget | null,
): HTMLTextAreaElement | null {
  return target instanceof HTMLTextAreaElement &&
    target.dataset.voiceDictate === "true"
    ? target
    : null;
}

function handleDictationKey(
  event: KeyboardEvent,
  editable: boolean,
  activation: "hold" | "toggle",
): void {
  const { sttAvailable, recordingMode, startVoice, stopVoice } =
    useVoice.getState();
  if (!sttAvailable) return;
  // A focused composer button (discard, confirm, end conversation) owns its own Space.
  if (recordingMode !== null && isButtonTarget(event.target)) return;
  if (editable) {
    const composer = composerTextarea(event.target);
    // Dictate from the composer only when it is empty (so a typed space still lands) or while
    // a dictation it started is running; every other focused field types the space.
    if (!composer || (recordingMode === null && composer.value.trim() !== ""))
      return;
  }
  event.preventDefault();
  if (recordingMode === null) startVoice("dictation");
  else if (recordingMode === "dictation" && activation === "toggle")
    stopVoice();
}

export function KeybindProvider({ children }: { children: ReactNode }) {
  const { cycleTheme } = useTheme();
  const activation = useVoiceActivation((s) => s.mode);

  useEffect(() => {
    // Space is the keyboard twin of the mic: it starts a dictation and confirms it, on
    // release (hold) or on the next press (toggle).
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const editable = isEditableTarget(event.target);

      if (event.key === " ") {
        handleDictationKey(event, editable, activation);
        return;
      }

      if (editable) return;
      if (event.key.toLowerCase() === "d") cycleTheme();
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
