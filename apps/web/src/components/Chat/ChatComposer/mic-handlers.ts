import type { PointerEvent } from "react";
import { type VoiceMode, useVoice } from "@/stores/use-voice";
import type { VoiceActivationMode } from "@/stores/use-preferences";

export interface MicHandlers {
  onClick?: () => void;
  onPointerDown?: (e: PointerEvent<HTMLButtonElement>) => void;
}

// Toggle: a click starts dictation and the confirm button sends it. Hold: pressing starts it
// and letting go anywhere confirms, so the release listens on the window because the mic
// itself gives way to the confirm/discard pair while dictating.

// Toggle: a click starts dictation and the confirm button sends it. Hold: pressing starts it
// and letting go anywhere confirms, so the release listens on the window because the mic
// itself gives way to the confirm/discard pair while dictating.

// Toggle: a click starts dictation and the confirm button sends it. Hold: pressing starts it
// and letting go anywhere confirms, so the release listens on the window because the mic
// itself gives way to the confirm/discard pair while dictating.
export function micHandlers(
  activation: VoiceActivationMode,
  startVoice: (mode: VoiceMode) => void,
  stopVoice: () => void,
): MicHandlers {
  if (activation === "toggle") {
    return {
      onClick: () => {
        startVoice("dictation");
      },
    };
  }
  return {
    onPointerDown: (e: PointerEvent<HTMLButtonElement>) => {
      e.preventDefault();
      startVoice("dictation");
      const release = () => {
        window.removeEventListener("pointerup", release);
        window.removeEventListener("pointercancel", release);
        if (useVoice.getState().recordingMode === "dictation") stopVoice();
      };
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);
    },
  };
}

// Expand a hair before the last word would wrap so the narrow field never shows two lines
// first; once expanded, hold until the text clearly fits again (hysteresis).

// Expand a hair before the last word would wrap so the narrow field never shows two lines
// first; once expanded, hold until the text clearly fits again (hysteresis).
export function expandedNext(
  prev: boolean,
  value: string,
  avail: number,
  width: number,
): boolean {
  if (value.trim().length === 0) return false;
  if (value.includes("\n")) return true;
  if (avail <= 0) return prev;
  return prev ? width > avail - 24 : width > avail - 8;
}
