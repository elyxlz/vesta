import type { ConnectionConfig } from "@/api/types";

export function changesGateway(
  current: ConnectionConfig | null,
  next: ConnectionConfig,
): boolean {
  return !current || current.url !== next.url || current.hosted !== next.hosted;
}
