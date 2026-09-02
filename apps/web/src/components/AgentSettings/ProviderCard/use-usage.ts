import { useResource } from "@vesta/core/react";
import { fetchUsage } from "@vesta/core";
import { httpClient } from "@/api/client";

/// Fetch an agent's normalized plan usage (the agent's GET /usage). Local to ProviderCard,
/// its only consumer.
export function useUsage(name: string | null) {
  const usage = useResource(name, (key) => fetchUsage(httpClient, key));
  return {
    usage: usage.data,
    loading: usage.loading,
    error: usage.error !== null,
    refresh: usage.reload,
  };
}
