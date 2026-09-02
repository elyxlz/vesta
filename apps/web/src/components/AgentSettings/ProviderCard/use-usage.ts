import { useResource } from "@vesta/core/react";
import { fetchUsage } from "@/api/agents";

/// Fetch an agent's normalized plan usage (the agent's GET /usage). Local to ProviderCard,
/// its only consumer.
export function useUsage(name: string | null) {
  const usage = useResource(name, fetchUsage);
  return {
    usage: usage.data,
    loading: usage.loading,
    error: usage.error !== null,
    refresh: usage.reload,
  };
}
