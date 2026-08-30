import { useCallback, useEffect, useState } from "react";
import {
  fetchPersonalities,
  fetchProviderCatalog,
  type PersonalityCatalog,
  type ProviderCatalog,
} from "@/api/catalogs";
import { errorMessage } from "@/lib/utils";

interface CatalogLoad<T> {
  data: T | undefined;
  error: string | null;
  retry: () => void;
}

function useCatalog<T>(
  agentName: string,
  fetchCatalog: (name: string) => Promise<T>,
  enabled: boolean,
): CatalogLoad<T> {
  const [data, setData] = useState<T | undefined>();
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!agentName || !enabled) {
      setData(undefined);
      setError(null);
      return;
    }
    let cancelled = false;
    setData(undefined);
    setError(null);
    fetchCatalog(agentName)
      .then((next) => {
        if (!cancelled) setData(next);
      })
      .catch((caught: unknown) => {
        if (!cancelled)
          setError(errorMessage(caught, "failed to load setup options"));
      });
    return () => {
      cancelled = true;
    };
  }, [agentName, attempt, enabled, fetchCatalog]);

  const retry = useCallback(() => setAttempt((value) => value + 1), []);
  return { data, error, retry };
}

export function useProviderCatalog(
  agentName: string,
  enabled = true,
): CatalogLoad<ProviderCatalog> {
  return useCatalog(agentName, fetchProviderCatalog, enabled);
}

export function usePersonalityCatalog(
  agentName: string,
  enabled = true,
): CatalogLoad<PersonalityCatalog> {
  return useCatalog(agentName, fetchPersonalities, enabled);
}
