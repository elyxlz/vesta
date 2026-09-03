import { useState } from "react";

interface LocalToggle {
  // The server value the flip was made against; the override holds only until the server moves.
  base: boolean | undefined;
  value: boolean;
}

/**
 * Optimistic boolean toggle that flips instantly in the UI and yields to the server value the
 * moment it changes, whether it caught up or was changed elsewhere.
 */
export function useOptimisticToggle(
  serverValue: boolean | undefined,
  defaultValue: boolean,
  onUpdate: (value: boolean) => void,
) {
  const [local, setLocal] = useState<LocalToggle | null>(null);
  const value =
    local !== null && local.base === serverValue
      ? local.value
      : (serverValue ?? defaultValue);

  const toggle = (v: boolean) => {
    setLocal({ base: serverValue, value: v });
    onUpdate(v);
  };

  return [value, toggle] as const;
}
