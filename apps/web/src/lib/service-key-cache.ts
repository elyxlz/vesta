import { createServiceKeyCache } from "@vesta/core";
import { httpClient } from "@/api/client";
import { getConnection } from "@/lib/connection";

// One cache per app instance, over the web client's own auth and refresh wiring. The gateway is
// read lazily from the live connection, exactly as httpClient resolves its base url, so
// reconnecting to another gateway mid-session mints fresh keys instead of reusing refused ones.
export const serviceKeys = createServiceKeyCache({
  http: httpClient,
  gateway: () => getConnection()?.url ?? null,
});
