import type { AlertDelta } from "@vesta/core";

// The only client-side notification rule (spec, amended): defer an alert for the agent the
// user is actively chatting with; a rate_limited alert always shows. Presentation content is
// the server preview.
export function shouldPresentAlert(
  delta: AlertDelta,
  activeAgent: string | null,
): boolean {
  if (delta.event.type === "rate_limited") return true;
  return delta.agent !== activeAgent;
}
