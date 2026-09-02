import { useEffect, useState } from "react";
import { native } from "@/lib/native";

function initialFocused(): boolean {
  if (typeof document === "undefined") return true;
  if (document.visibilityState === "hidden") return false;
  if (typeof document.hasFocus === "function") return document.hasFocus();
  return true;
}

export function useWindowFocus(): boolean {
  const [focused, setFocused] = useState<boolean>(initialFocused);

  useEffect(() => {
    const onFocus = () => setFocused(true);
    const onBlur = () => setFocused(false);
    const onVisibility = () => {
      if (document.visibilityState === "visible")
        setFocused(document.hasFocus());
      else setFocused(false);
    };

    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    document.addEventListener("visibilitychange", onVisibility);
    const unlistenNative = native.onWindowFocusChange(setFocused);

    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      document.removeEventListener("visibilitychange", onVisibility);
      unlistenNative();
    };
  }, []);

  return focused;
}
