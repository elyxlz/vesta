import { useCallback, useSyncExternalStore } from "react";

// Subscribe to a CSS media query, re-rendering when it changes. The first render already reads
// the current match, so nothing flashes a default.
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
  );
}
