import type { UserNotificationDelta } from "@vesta/core";

// The only client-side notification rule (spec, amended): defer a user notification for the agent the
// user is actively chatting with; a rate_limited or auth_lost user notification always shows, because
// the chat surface shows nothing for the turn that failed. Presentation content is the server-decided
// title/body.
export function shouldPresentUserNotification(
  delta: UserNotificationDelta,
  activeAgent: string | null,
): boolean {
  if (delta.kind === "rate_limited" || delta.kind === "auth_lost") return true;
  return delta.agent !== activeAgent;
}
