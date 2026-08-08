import { useEffect, useState } from "react";
import type { OpenRouterModelOption } from "@/api/providers/openrouter";

/// The live Claude catalog as picker options. `key` is whatever the fetch needs (the
/// agent name in settings, the OAuth blob during onboarding); null disables the fetch.
/// Returns null while loading, [] on failure or an empty catalog (which degrades the
/// picker to the alias buttons alone). The result is remembered per key, so a slow
/// response from an abandoned auth can never stand in for a later account's catalog.
export function useClaudeModels(
  key: string | null,
  fetchModels: (key: string) => Promise<OpenRouterModelOption[]>,
): OpenRouterModelOption[] | null {
  const [result, setResult] = useState<{
    key: string;
    models: OpenRouterModelOption[];
  } | null>(null);
  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    fetchModels(key)
      .then((models) => {
        if (!cancelled) setResult({ key, models });
      })
      .catch(() => {
        if (!cancelled) setResult({ key, models: [] });
      });
    return () => {
      cancelled = true;
    };
  }, [key, fetchModels]);
  return result !== null && result.key === key ? result.models : null;
}
