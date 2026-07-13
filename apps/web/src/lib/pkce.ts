// Hosted login handoff (OAuth Authorization Code + PKCE) against the vesta.run
// control plane (issue #19). A hosted user never receives the per-VM api_key;
// instead the control plane mints the short-lived api_key JWT vestad accepts and
// hands it back over a PKCE-protected back channel.
//
//   this page (<sub>.vesta.run, no token)
//     → GET https://vesta.run/api/authorize?client_id=<sub>&redirect_uri=<origin>/cb&...
//     ← 302 <origin>/cb?code=...&state=...
//     → POST https://vesta.run/api/token { code, code_verifier }   (back channel)
//     ← { access_token, expires_in }
//
// The token never rides in a URL; only the single-use, PKCE-bound code does.
//
// The desktop app isn't served by a box, so it can't full-navigate to /cb on
// its own origin. It instead runs a transient loopback server (the Electron
// main process, via the runtime bridge) and registers
// `http://127.0.0.1:<port>/cb` as the redirect; the control plane returns the
// box `url` alongside the token, and we upgrade that token to a rotating
// refresh at the box's `/auth/exchange`. See `startNativeLogin` and the
// `vesta-app` native client in the control plane's functions/api/oauth.ts.

import { native } from "./native";
import { setConnection } from "./connection";

const VERIFIER_KEY = "vesta-pkce-verifier";
const STATE_KEY = "vesta-pkce-state";

/** Control-plane apex for native apps (which have no box-derived host). */
const CONTROL_APEX = "https://vesta.run";
/** Native OAuth client_id the control plane recognises (functions/api/oauth.ts). */
const NATIVE_CLIENT_ID = "vesta-app";

function base64url(bytes: Uint8Array): string {
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function randomBase64url(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  crypto.getRandomValues(bytes);
  return base64url(bytes);
}

async function s256(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(verifier),
  );
  return base64url(new Uint8Array(digest));
}

/** The control-plane apex + this box's subdomain, derived from the page host. */
export function tenantIdentity(): { apexOrigin: string; subdomain: string } {
  const host = window.location.hostname; // e.g. alice.vesta.run
  const firstDot = host.indexOf(".");
  const subdomain = firstDot === -1 ? host : host.slice(0, firstDot);
  const apex = firstDot === -1 ? host : host.slice(firstDot + 1);
  return { apexOrigin: `https://${apex}`, subdomain };
}

/**
 * Begin the hosted login: stash a fresh PKCE verifier + CSRF state, then
 * full-navigate to the control plane's /api/authorize. Returns nothing — the
 * browser leaves this page.
 */
export async function startHostedLogin(): Promise<void> {
  // The desktop app can't redirect to its own origin: hand off to the
  // loopback flow instead.
  if (native.oauthLoopback) return startNativeLogin();

  const { apexOrigin, subdomain } = tenantIdentity();
  const verifier = randomBase64url(32);
  const state = randomBase64url(16);
  // sessionStorage so the verifier survives the redirect but not a new tab/session.
  sessionStorage.setItem(VERIFIER_KEY, verifier);
  sessionStorage.setItem(STATE_KEY, state);

  const params = new URLSearchParams({
    client_id: subdomain,
    redirect_uri: `${window.location.origin}/cb`,
    code_challenge: await s256(verifier),
    code_challenge_method: "S256",
    state,
  });
  window.location.assign(`${apexOrigin}/api/authorize?${params.toString()}`);
}

export interface HostedToken {
  accessToken: string;
  expiresIn: number;
}

/**
 * Complete the hosted login at /cb: validate the returned state, exchange the
 * code + stored verifier for an access token over the back channel. Throws on
 * any mismatch or failure (the caller surfaces it).
 */
export async function completeHostedLogin(
  code: string,
  returnedState: string,
): Promise<HostedToken> {
  const verifier = sessionStorage.getItem(VERIFIER_KEY);
  const state = sessionStorage.getItem(STATE_KEY);
  sessionStorage.removeItem(VERIFIER_KEY);
  sessionStorage.removeItem(STATE_KEY);

  if (!verifier || !state) throw new Error("login session expired, try again");
  if (returnedState !== state) throw new Error("state mismatch, try again");

  const { apexOrigin } = tenantIdentity();
  const resp = await fetch(`${apexOrigin}/api/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, code_verifier: verifier }),
  });
  if (!resp.ok) throw new Error("could not complete sign-in");
  const data = await resp.json();
  if (!data.access_token) throw new Error("no token returned");
  return { accessToken: data.access_token, expiresIn: data.expires_in ?? 600 };
}

/**
 * Native (desktop app) hosted login. The main process spins up a loopback
 * server, the system browser opens the control plane's single sign-in page,
 * and the redirect lands there — no box origin to bounce off.
 *
 *   loopback :<port>  →  open https://vesta.run/api/authorize?client_id=vesta-app
 *                        &redirect_uri=http://127.0.0.1:<port>/cb&...
 *     ← callback: http://127.0.0.1:<port>/cb?code=...&state=...
 *     → POST https://vesta.run/api/token { code, code_verifier }
 *     ← { access_token, url }                       (url = this user's box)
 *     → POST <url>/auth/exchange  (Bearer access_token)
 *     ← { access_token, refresh_token, expires_in } (rotating, on-box)
 */
export async function startNativeLogin(): Promise<void> {
  const loopback = native.oauthLoopback;
  if (!loopback) throw new Error("native sign-in requires the desktop app");

  const verifier = randomBase64url(32);
  const state = randomBase64url(16);
  const port = await loopback.start();
  const params = new URLSearchParams({
    client_id: NATIVE_CLIENT_ID,
    redirect_uri: `http://127.0.0.1:${port}/cb`,
    code_challenge: await s256(verifier),
    code_challenge_method: "S256",
    state,
  });

  // Bridge the loopback's callback (which fires when the browser redirects
  // back, potentially much later) into this promise, so the caller can surface
  // errors and reset its busy state. A success ends in a full navigation into the
  // app. `settled` guards against double-firing — the loopback can see a stray
  // favicon/preflight hit before the real callback.
  await new Promise<void>((resolve, reject) => {
    let settled = false;
    let unlisten = () => {};
    const teardown = () => {
      void loopback.cancel(port).catch(() => {});
      unlisten();
    };

    unlisten = loopback.onCallback((url: string) => {
      if (settled) return;
      const u = new URL(url);
      const code = u.searchParams.get("code");
      const returnedState = u.searchParams.get("state");
      if (!code || !returnedState) return; // stray hit — keep waiting
      settled = true;
      void (async () => {
        try {
          if (returnedState !== state) {
            throw new Error("state mismatch, try again");
          }
          await completeNativeLogin(code, verifier);
          teardown();
          resolve();
          // Full load so connection-reading providers re-init from storage.
          window.location.assign("/");
        } catch (e) {
          teardown();
          reject(e instanceof Error ? e : new Error(String(e)));
        }
      })();
    });

    native
      .openExternal(`${CONTROL_APEX}/api/authorize?${params.toString()}`)
      .catch((e: unknown) => {
        if (settled) return;
        settled = true;
        teardown();
        reject(e instanceof Error ? e : new Error(String(e)));
      });
  });
}

/**
 * Finish a native login: code → control-plane access token + box url, then
 * upgrade that token to a rotating refresh at the box's /auth/exchange and
 * persist the connection. Throws on any failure (the caller surfaces it).
 */
async function completeNativeLogin(
  code: string,
  verifier: string,
): Promise<void> {
  const tokenResp = await fetch(`${CONTROL_APEX}/api/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, code_verifier: verifier }),
  });
  if (!tokenResp.ok) throw new Error("could not complete sign-in");
  const tok = await tokenResp.json();
  if (!tok.access_token || !tok.url) {
    throw new Error("sign-in response missing token or box url");
  }

  const exchangeResp = await fetch(`${tok.url}/auth/exchange`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${tok.access_token}`,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!exchangeResp.ok) {
    throw new Error("could not finish connecting to your vesta");
  }
  const ex = await exchangeResp.json();
  if (!ex.access_token || !ex.refresh_token) {
    throw new Error("exchange returned no tokens");
  }
  setConnection(
    tok.url,
    ex.access_token,
    ex.refresh_token,
    ex.expires_in ?? 3600,
  );
}
