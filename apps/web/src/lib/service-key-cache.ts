import { createServiceKeyCache } from "@vesta/core";
import { httpClient } from "@/api/client";

// One cache per app instance, over the web client's own auth and refresh wiring.
export const serviceKeys = createServiceKeyCache({ http: httpClient });
