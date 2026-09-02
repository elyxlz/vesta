import { getConnection, setConnection } from "@/lib/connection";
import { numberField, stringField } from "@/lib/json-shape";
import { rememberGatewayAfterConnect } from "@/lib/recent-gateways";
import { jsonInit } from "./client";

export async function connectToServer(
  url: string,
  apiKey: string,
): Promise<void> {
  const normalized = url.replace(/\/+$/, "");

  const healthResp = await fetch(`${normalized}/health`).catch(() => null);
  if (!healthResp?.ok) {
    throw new Error("could not reach server");
  }

  const resp = await fetch(
    `${normalized}/auth/session`,
    jsonInit("POST", { api_key: apiKey }),
  );

  if (!resp.ok) {
    throw new Error(
      resp.status === 401 ? "invalid api key" : "session creation failed",
    );
  }

  const data: unknown = await resp.json();
  const accessToken = stringField(data, "access_token");
  const refreshToken = stringField(data, "refresh_token");
  const expiresIn = numberField(data, "expires_in");
  if (accessToken === null || refreshToken === null || expiresIn === null)
    throw new Error("session response missing tokens");
  setConnection(normalized, accessToken, refreshToken, expiresIn);
  const connection = getConnection();
  if (connection) await rememberGatewayAfterConnect(connection);
}
