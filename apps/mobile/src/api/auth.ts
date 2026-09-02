import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import {
  GATEWAY_CONNECT_TIMEOUT_MS,
  mintConnection,
  normalizeGatewayUrl,
  refreshConnection,
  type ConnectionConfig,
} from "@vesta/core";

export const cloudSignInEnabled =
  Constants.expoConfig?.extra?.cloudSignInEnabled === true;

const CONTROL_APEX = "https://vesta.run";
const NATIVE_CLIENT_ID = "vesta-app";
const UNIVERSAL_REDIRECT = "https://vesta.run/mobile/oauth/callback";
const DEVELOPMENT_REDIRECT = "vesta://oauth/callback";

function base64Url(value: string): string {
  return value.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function pkcePair(): Promise<{
  verifier: string;
  challenge: string;
}> {
  const verifier = `${Crypto.randomUUID()}${Crypto.randomUUID()}`.replace(
    /-/g,
    "",
  );
  const digest = await Crypto.digestStringAsync(
    Crypto.CryptoDigestAlgorithm.SHA256,
    verifier,
    { encoding: Crypto.CryptoEncoding.BASE64 },
  );
  return { verifier, challenge: base64Url(digest) };
}

// The apex (vesta.run) account sign-in: a PKCE authorize in a private browser session, the apex
// token exchanged at the user's gateway for a session that refreshes like a keyed one.
export async function signInWithVestaAccount(): Promise<ConnectionConfig | null> {
  const redirectUri = __DEV__ ? DEVELOPMENT_REDIRECT : UNIVERSAL_REDIRECT;
  const state = Crypto.randomUUID();
  const { verifier, challenge } = await pkcePair();
  const parameters = new URLSearchParams({
    client_id: NATIVE_CLIENT_ID,
    redirect_uri: redirectUri,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });

  const result = await WebBrowser.openAuthSessionAsync(
    `${CONTROL_APEX}/api/authorize?${parameters.toString()}`,
    redirectUri,
    { preferEphemeralSession: true },
  );
  if (result.type === "cancel" || result.type === "dismiss") return null;
  if (result.type !== "success") throw new Error("Sign-in failed");

  const callback = new URL(result.url);
  const code = callback.searchParams.get("code");
  const returnedState = callback.searchParams.get("state");
  if (!code || returnedState !== state) {
    throw new Error("The sign-in response could not be verified.");
  }

  const tokenResponse = await fetch(`${CONTROL_APEX}/api/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, code_verifier: verifier }),
  });
  if (!tokenResponse.ok) throw new Error("Could not finish account sign-in.");
  const token: { access_token?: string; url?: string } =
    await tokenResponse.json();
  if (!token.access_token || !token.url) {
    throw new Error("The sign-in response did not include a gateway.");
  }

  const exchangeResponse = await fetch(`${token.url}/auth/exchange`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token.access_token}`,
      "Content-Type": "application/json",
    },
    body: "{}",
  });
  if (!exchangeResponse.ok) {
    throw new Error("Could not establish a gateway session.");
  }
  const exchange: {
    access_token: string;
    refresh_token: string;
    expires_in?: number;
  } = await exchangeResponse.json();
  return {
    url: normalizeGatewayUrl(token.url),
    accessToken: exchange.access_token,
    refreshToken: exchange.refresh_token,
    expiresAt: Date.now() + (exchange.expires_in ?? 3600) * 1000,
    hosted: true,
  };
}

// Exchange a connect key for a session (core owns the wire flow and its reachability budget,
// GATEWAY_CONNECT_TIMEOUT_MS).
export function connectWithKey(
  url: string,
  apiKey: string,
): Promise<ConnectionConfig> {
  return mintConnection((input, init) => fetch(input, init), url, apiKey);
}

export { GATEWAY_CONNECT_TIMEOUT_MS };

// Revive a saved gateway session before reconnecting to it; an expired or refresh-less one asks
// for a fresh connect instead.
export async function resumeGatewaySession(
  connection: ConnectionConfig,
): Promise<ConnectionConfig> {
  const expired = new Error(
    "This saved gateway session has expired. Connect to it again.",
  );
  if (!connection.refreshToken) throw expired;
  const outcome = await refreshConnection(
    (input, init) => fetch(input, init),
    connection,
  );
  if (outcome.kind === "expired") throw expired;
  if (outcome.kind === "transient") {
    throw new Error("Could not restore this saved gateway session.");
  }
  return outcome.connection;
}
