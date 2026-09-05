import { directRoomId, type UserNotificationDelta } from "@vesta/core";

// The only client-side notification rule (spec, amended): defer a user notification for the
// conversation the user is reading; a rate_limited or needs_user user notification always shows,
// since neither has a visible counterpart in the open chat. Presentation content is the
// server-decided title/body.
export function shouldPresentUserNotification(
  delta: UserNotificationDelta,
  activeRoom: string | null,
): boolean {
  // LEGACY(remove-when: no supported gateway emits kind=rate_limited; it was
  // renamed needs_user in the release that added the durable notification log):
  if (delta.kind === "rate_limited" || delta.kind === "needs_user") return true;
  // A reply names the room it landed in; a notice about the agent itself (a finished task) names
  // none, so it belongs to that agent's own conversation.
  return (delta.room ?? directRoomId(delta.agent)) !== activeRoom;
}
