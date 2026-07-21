import type { UserNotificationDelta } from "@vesta/core";

// The only client-side notification rule (spec, amended): defer a user notification for the agent the
// user is actively chatting with; a rate_limited user notification always shows. Presentation content
// is the server-decided title/body.
export function shouldPresentUserNotification(
  delta: UserNotificationDelta,
  activeAgent: string | null,
): boolean {
  if (delta.kind === "rate_limited") return true;
  return delta.agent !== activeAgent;
}
