import { jsonInit, type HttpClient } from "../transport/http";
import { agentPath } from "./agents";

// One match condition over a notification field. `field` is a concrete notification key (chat_name,
// chat_type, ...) or an alias ("sender" = the identity fields, "text" = body/message). `op` is a
// case-insensitive substring ("contains") or regex; `negate` inverts it. Mirrors the agent's
// FieldPredicate.
export interface FieldPredicate {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate?: boolean;
}

export interface NotificationInterruptRule {
  id: string;
  source?: string | null;
  type?: string | null;
  // All conditions beyond source/type (sender, keyword, and any arbitrary field) are predicates
  // here, ANDed together. Empty = the rule matches every notification of the given source/type.
  match?: FieldPredicate[];
  action: "interrupt" | "snooze" | "trash";
}

// Read the agent's ordered notification interrupt ruleset from its config (GET /config).
export async function getNotificationInterruptRules(
  http: HttpClient,
  name: string,
): Promise<NotificationInterruptRule[]> {
  const response = await http.json<{
    notification_rules?: NotificationInterruptRule[];
  }>(agentPath(name, "/config"));
  return response.notification_rules ?? [];
}

// Replace the ruleset on the agent's config (PUT /config with {notification_rules}). Live: the agent
// applies it on its next tick, no restart. Rule ids are generated client-side, so the saved rules
// are exactly what was sent.
export async function setNotificationInterruptRules(
  http: HttpClient,
  name: string,
  rules: NotificationInterruptRule[],
): Promise<NotificationInterruptRule[]> {
  await http.request(
    agentPath(name, "/config"),
    jsonInit("PUT", { notification_rules: rules }),
  );
  return rules;
}
