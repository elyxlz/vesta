import { useGlobalSearchParams, useSegments } from "expo-router";

// The agent whose page is open, or null on any other screen.
export function useViewedAgent(): string | null {
  const segments = useSegments();
  const { name } = useGlobalSearchParams<{ name?: string }>();
  return segments[0] === "agent" && name !== undefined ? name : null;
}
