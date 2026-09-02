import { useResource } from "@vesta/core/react";
import { loadFailure } from "@/lib/utils";
import { fetchPersonalities, fetchProviderCatalog } from "@vesta/core";
import type {
  HttpClient,
  PersonalityCatalog,
  ProviderCatalog,
} from "@vesta/core";
import { httpClient } from "@/api/client";

interface CatalogLoad<T> {
  data: T | undefined;
  error: string | null;
  retry: () => void;
}

function useCatalog<T>(
  agentName: string,
  fetchCatalog: (http: HttpClient, name: string) => Promise<T>,
  enabled: boolean,
): CatalogLoad<T> {
  const catalog = useResource(agentName && enabled ? agentName : null, (name) =>
    fetchCatalog(httpClient, name),
  );
  return {
    data: catalog.data ?? undefined,
    error: loadFailure(catalog.error, "failed to load setup options"),
    retry: catalog.reload,
  };
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
