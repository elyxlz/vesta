import { useEffect, useState } from "react";
import { isTauri } from "@/lib/env";

function initialFocused(): boolean {
  if (typeof document === "undefined") return true;
  if (document.visibilityState === "hidden") return false;
  if (typeof document.hasFocus === "function") return document.hasFocus();
  return true;
}

export function useWindowFocus(): boolean {
  const [focused, setFocused] = useState<boolean>(initialFocused);

  useEffect(() => {
    let disposed = false;
    let unlistenTauri: (() => void) | null = null;

    const onFocus = () => setFocused(true);
    const onBlur = () => setFocused(false);
    const onVisibility = () => {
      if (document.visibilityState === "visible") setFocused(document.hasFocus());
      else setFocused(false);
    };

    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibility);

    if (isTauri) {
      import("@tauri-apps/api/window").then(({ getCurrentWindow }) => {
        if (disposed) return;
        const w = getCurrentWindow();
        w.onFocusChanged(({ payload }) => setFocused(payload)).then((fn) => {
          if (disposed) fn();
          else unlistenTauri = fn;
        });
      });
    }

    return () => {
      disposed = true;
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibility);
      if (unlistenTauri) unlistenTauri();
    };
  }, []);

  return focused;
}
