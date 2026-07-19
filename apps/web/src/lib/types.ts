import type {
  AgentInfo as AgentNodeInfo,
  ReleaseChannel,
  VestaEvent,
} from "@vesta/core";

// The roster row as the web app holds it: core's per-agent node info plus the `name` the tree keys
// agents by (core's AgentInfo carries no name of its own).
export type AgentRow = AgentNodeInfo & { name: string };

// A chat row as the view holds it. Core's VestaEvent is the wire shape (server `id` always present);
// a view row may instead be an optimistic user bubble (no persisted id yet) carrying `intent_id` /
// `send_state` to track its unconfirmed POST until the append echo confirms it. Synthetic rows
// (Debug gallery, tests) likewise carry no id, so `id` is optional on every member.
type LooseId<T> = T extends unknown ? Omit<T, "id"> & { id?: number } : never;
export type ChatMessage =
  | Exclude<LooseId<VestaEvent>, { type: "user" }>
  | (Extract<LooseId<VestaEvent>, { type: "user" }> & {
      intent_id?: string;
      send_state?: "sending" | "retry" | "failed";
    });

export type LogEvent =
  | { kind: "Line"; text: string }
  | { kind: "End" }
  | { kind: "Error"; message: string };

export interface GatewayVersionInfo {
  version: string;
  api_compat: string;
  dev_mode: boolean;
  latest_version: string | null;
  update_available: boolean | null;
  channel?: ReleaseChannel;
  auto_update?: boolean;
}
