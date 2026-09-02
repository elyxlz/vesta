import type { OpenRouterModelOption } from "@vesta/core";
import { useResource } from "@vesta/core/react";

/// The live Claude catalog as picker options. `key` is whatever the fetch needs (the
/// agent name in settings, the OAuth blob during onboarding); null disables the fetch.
/// Returns null while loading, [] on failure or an empty catalog (which degrades the
/// picker to the alias buttons alone). The result is remembered per key, so a slow
/// response from an abandoned auth can never stand in for a later account's catalog.
export function useClaudeModels(
  key: string | null,
  fetchModels: (key: string) => Promise<OpenRouterModelOption[]>,
): OpenRouterModelOption[] | null {
  const models = useResource(key, fetchModels);
  if (key === null || models.loading) return null;
  return models.error === null ? (models.data ?? []) : [];
}
