import { useCallback, useEffect, useState } from "react";

// vestad answers a request before the agent has moved, and the roster reports the move a moment
// later. After each request, give up on a leg the roster never shows instead of staying busy.
const ROUND_TRIP_LEG_TIMEOUT_MS = 20_000;

type Leg = "away" | "back" | null;

// Tracks a roster round trip after a request: busy from the request until the observed state has
// gone `away` (restarting, backing up) and come back, each leg bounded by a timeout.
export function useAwaitedRoundTrip(away: boolean): {
  busy: boolean;
  start: () => void;
} {
  const [leg, setLeg] = useState<Leg>(null);

  // The legs advance with the observed value, so they resolve in the render that sees the change.
  if (leg === "away" && away) setLeg("back");
  if (leg === "back" && !away) setLeg(null);

  const start = useCallback(() => {
    setLeg("away");
  }, []);

  useEffect(() => {
    if (leg === null) return;
    const timeout = setTimeout(() => {
      setLeg(null);
    }, ROUND_TRIP_LEG_TIMEOUT_MS);
    return () => {
      clearTimeout(timeout);
    };
  }, [leg]);

  return { busy: leg !== null, start };
}
