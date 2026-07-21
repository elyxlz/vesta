import type { VestaEvent } from "@vesta/core";

// The roster row: core is the one owner (`AgentInfo & { name }`); re-exported so web consumers keep
// their `@/lib/types` import path.
export type { AgentRow } from "@vesta/core";

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
