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

const VERIFIER_KEY = "vesta-pkce-verifier";
const STATE_KEY = "vesta-pkce-state";

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
