import { ApiError, createSession } from "@vesta/core";
import { getConnection, restoreConnection } from "@/lib/connection";
import { startHostedLogin } from "@/lib/pkce";

// The web app's one gateway session, built over the connection store the native bridge persists.
// @vesta/core owns the refresh, the expiry buffer, the token-in-URL carriers, and the http client;
// web injects only persistence and the hosted re-authorization bounce (the apex session cookie is
// the refresh root, so a hosted connection with no refresh token re-runs the PKCE flow).
export const session = createSession({
  fetch: (input, init) => fetch(input, init),
  read: getConnection,
  write: restoreConnection,
  reauthorize: () => {
    void startHostedLogin();
  },
});

// The single web-side HttpClient. Every api/* wrapper binds it, and the controller shares it.
export const httpClient = session.http;
export const authedUrl = session.authedUrl;
export const websocketUrl = session.websocketUrl;

export { ApiError };
