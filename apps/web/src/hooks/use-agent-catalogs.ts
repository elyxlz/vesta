import { useResource } from "@vesta/core/react";
import {
  fetchPersonalities,
  fetchProviderCatalog,
  type PersonalityCatalog,
  type ProviderCatalog,
} from "@/api/catalogs";
import { loadFailure } from "@/lib/utils";

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
  const catalog = useResource(
    agentName && enabled ? agentName : null,
    fetchCatalog,
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
