import { createServiceKeyCache, type ServiceKeyCache } from "@vesta/core";
import type { ApiClient } from "@/api/client";

// Mobile builds its api client inside the session provider rather than as a module singleton,
// so the cache hangs off the client: the same client keeps reusing its own keys, and a client
// built by a test never shares them. Reconnecting to another gateway keeps the client, which is
// why the gateway is read lazily below and forms part of the cache identity inside core.
const caches = new WeakMap<ApiClient, ServiceKeyCache>();

export function serviceKeyCacheFor(api: ApiClient): ServiceKeyCache {
  const existing = caches.get(api);
  if (existing) return existing;
  const created = createServiceKeyCache({
    http: { request: api.request, json: api.json },
    gateway: () => api.getConnection()?.url ?? null,
  });
  caches.set(api, created);
  return created;
}
