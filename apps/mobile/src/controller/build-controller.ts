import { createController, type Controller, type Session } from "@vesta/core";

// The controller over the app's one session (the api client's): it dials the session's
// token-stamped /sync URL, shares its http client, and rotates the token in-band before it expires,
// so a token rotation never tears the controller down and only a gateway switch rebuilds it.
export function buildController(
  session: Session,
  clientVersion?: string,
  device?: { id: string; descriptor: string },
): Controller {
  return createController({
    session,
    sync: {
      setTimer: (fn, ms) => setTimeout(fn, ms) as unknown as number,
      clearTimer: (handle) => clearTimeout(handle),
      clientVersion,
      clientKind: "mobile",
      device,
    },
  });
}
