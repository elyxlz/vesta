import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import type { ConnectionConfig } from "./types";

const CONTROL_APEX = "https://vesta.run";
const NATIVE_CLIENT_ID = "vesta-app";
const UNIVERSAL_REDIRECT = "https://vesta.run/mobile/oauth/callback";
const DEVELOPMENT_REDIRECT = "vesta://oauth/callback";
const GATEWAY_CONNECT_TIMEOUT_MS = 8_000;

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
  if (result.type !== "success") throw new Error("Could not complete sign-in.");

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
    url: token.url.replace(/\/+$/, ""),
    accessToken: exchange.access_token,
    refreshToken: exchange.refresh_token,
    expiresAt: Date.now() + (exchange.expires_in ?? 3600) * 1000,
    hosted: true,
  };
}

export async function connectWithKey(
  url: string,
  apiKey: string,
): Promise<ConnectionConfig> {
  await assertGatewayReachable(url);
  const response = await fetchGateway(`${url}/auth/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
  if (!response.ok) {
    throw new Error(
      response.status === 401
        ? "This connection key is invalid."
        : "Could not create a gateway session.",
    );
  }
  const session: {
    access_token: string;
    refresh_token: string;
    expires_in: number;
  } = await response.json();
  return {
    url,
    accessToken: session.access_token,
    refreshToken: session.refresh_token,
    expiresAt: Date.now() + session.expires_in * 1000,
    hosted: false,
  };
}

export async function resumeGatewaySession(
  connection: ConnectionConfig,
): Promise<ConnectionConfig> {
  if (!connection.refreshToken) {
    throw new Error(
      "This saved gateway session has expired. Connect to it again.",
    );
  }
  const response = await fetchGateway(`${connection.url}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: connection.refreshToken }),
  });
  if (response.status === 401) {
    throw new Error(
      "This saved gateway session has expired. Connect to it again.",
    );
  }
  if (!response.ok) {
    throw new Error("Could not restore this saved gateway session.");
  }
  const session: {
    access_token?: string;
    refresh_token?: string;
    expires_in?: number;
  } = await response.json();
  if (!session.access_token || !session.refresh_token) {
    throw new Error("Could not restore this saved gateway session.");
  }
  return {
    ...connection,
    accessToken: session.access_token,
    refreshToken: session.refresh_token,
    expiresAt: Date.now() + (session.expires_in ?? 3600) * 1000,
  };
}

export async function assertGatewayReachable(url: string): Promise<void> {
  const health = await fetchGateway(`${url}/health`);
  if (!health.ok) throw new Error("Could not reach this Vesta gateway.");
}

async function fetchGateway(
  url: string,
  init?: RequestInit,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(
    () => controller.abort(),
    GATEWAY_CONNECT_TIMEOUT_MS,
  );
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch {
    throw new Error("Could not reach this Vesta gateway.");
  } finally {
    clearTimeout(timeout);
  }
}
