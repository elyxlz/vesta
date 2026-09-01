import { useCallback, useEffect, useState } from "react";
import { native } from "@/lib/native";

export interface LoginItemToggle {
  /** True only in the desktop app; the browser cannot set an OS login item. */
  supported: boolean;
  enabled: boolean;
  setEnabled: (value: boolean) => Promise<void>;
}

// Drives the "launch on startup" toggle from the OS login item. Reads the current state once on
// mount; the browser build reports supported=false and no-ops.
export function useLoginItem(): LoginItemToggle {
  const loginItem = native.loginItem;
  const [enabled, setEnabledState] = useState(false);

  useEffect(() => {
    if (!loginItem) return;
    void loginItem.get().then(setEnabledState);
  }, [loginItem]);

  const setEnabled = useCallback(
    async (value: boolean) => {
      if (!loginItem) return;
      setEnabledState(value);
      await loginItem.set(value);
    },
    [loginItem],
  );

  return { supported: loginItem !== null, enabled, setEnabled };
}
