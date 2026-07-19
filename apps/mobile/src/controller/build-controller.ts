import { createController, type Controller } from "@vesta/core";
import type { ConnectionConfig } from "@/api/types";
import { createRnSocket } from "./rn-socket";

// The controller's view of the session: a LIVE connection accessor (base URL + token, read
// fresh on every socket build and http call) and the single force-refresh path owned by
// SessionProvider's api client. Reading live means a token rotation reauths in-band instead
// of tearing the controller down. No second refresh impl.
export interface ControllerSession {
  getConnection: () => ConnectionConfig | null;
  refreshAccessToken: () => Promise<boolean>;
}

export function buildController(session: ControllerSession): Controller {
  const conn = () => session.getConnection();
  const syncUrl = () => {
    const current = conn();
    if (!current) throw new Error("not connected to a Vesta gateway");
    const base = current.url.replace(/^http/, "ws");
    return `${base}/sync?token=${encodeURIComponent(current.accessToken)}`;
  };
  return createController({
    sync: {
      buildUrl: syncUrl,
      createSocket: createRnSocket,
      setTimer: (fn, ms) => setTimeout(fn, ms) as unknown as number,
      clearTimer: (handle) => clearTimeout(handle),
    },
    http: {
      baseUrl: conn()?.url ?? "",
      fetch: (input, init) => fetch(input, init),
      token: () => conn()?.accessToken ?? null,
      refresh: () => session.refreshAccessToken(),
    },
  });
}
