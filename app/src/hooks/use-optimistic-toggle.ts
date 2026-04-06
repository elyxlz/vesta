import { useEffect, useState } from "react";

/**
 * Optimistic boolean toggle that flips instantly in the UI
 * and syncs back when the server value catches up.
 */
export function useOptimisticToggle(
  serverValue: boolean | undefined,
  defaultValue: boolean,
  onUpdate: (value: boolean) => void,
) {
  const [local, setLocal] = useState<boolean | null>(null);
  const value = local ?? serverValue ?? defaultValue;

  useEffect(() => {
    if (serverValue !== undefined && local === serverValue) setLocal(null);
  }, [serverValue, local]);

  const toggle = (v: boolean) => {
    setLocal(v);
    onUpdate(v);
  };

  return [value, toggle] as const;
}
