import type { ConnectionConfig } from "@/lib/connection";
import { parseGatewayUrl } from "@/lib/gateway-url";

/** Validate a stored connection before either bridge trusts it: both tokens present
 * (or hosted, where the apex cookie replaces the refresh token) and the url reduced
 * to a safe http(s) origin, since consumers connect and navigate to it. */
export function parseConnectionConfig(value: unknown): ConnectionConfig | null {
  if (value === null || typeof value !== "object") return null;
  const config = value as ConnectionConfig;
  if (!config.accessToken || !(config.refreshToken || config.hosted))
    return null;
  const url = parseGatewayUrl(config.url);
  if (url === null) return null;
  return { ...config, url };
}
