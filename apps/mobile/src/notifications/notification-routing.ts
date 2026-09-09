import { directRoomId } from "@vesta/core";

export interface PendingNotification {
  identifier: string;
  agent: string;
  eventType: string;
  gateway: string | null;
  // The conversation the push points at, resolved from the route the gateway stamped on it.
  room: string;
}

// Where a push belongs, read off the route the gateway stamped, which spells the room id exactly
// as the node holds it: `/chat/<id>` names a room, an `/agent/<name>` route (a reply in that
// agent's direct chat, or news about the agent itself) that agent's own conversation. A push from
// a gateway that stamped no route at all answers the same direct room, which is where it used to
// land.
export function pushRoom(route: unknown, agent: string): string {
  if (typeof route === "string") {
    const segments = route.split("/").filter((segment) => segment.length > 0);
    const [head, id] = segments;
    if (head === "chat" && id !== undefined) return id;
  }
  return directRoomId(agent);
}

// Which screen opens the push: the agent page for a direct room (the chat pager is that page), the
// room screen for anything else.
export function pushOpensAgentPage(pending: PendingNotification): boolean {
  return pending.room === directRoomId(pending.agent);
}

export function pendingNotificationFromData(
  data: Record<string, unknown> | null | undefined,
  identifier: string,
): PendingNotification | null {
  if (!data || typeof data.agent !== "string" || !data.agent.trim()) {
    return null;
  }
  const agent = data.agent.trim();
  return {
    identifier,
    agent,
    eventType: typeof data.eventType === "string" ? data.eventType : "",
    gateway:
      typeof data.gateway === "string" && data.gateway ? data.gateway : null,
    room:
      typeof data.room === "string" ? data.room : pushRoom(data.route, agent),
  };
}

export function readPendingNotification(
  stored: string | null,
): PendingNotification | null {
  if (!stored) return null;
  try {
    const parsed: Record<string, unknown> = JSON.parse(stored);
    return pendingNotificationFromData(
      parsed,
      typeof parsed.identifier === "string" ? parsed.identifier : "stored",
    );
  } catch {
    return null;
  }
}

export type NotificationNavigationDecision = "wait" | "discard" | "open";

export function notificationNavigationDecision(input: {
  pending: PendingNotification;
  sessionStatus: "booting" | "disconnected" | "connected";
  reachable: boolean;
  agentsReady: boolean;
  agentNames: readonly string[];
  routeReady: boolean;
  currentGateway: string | null;
  viewingAgent: string | null;
}): NotificationNavigationDecision {
  if (
    input.sessionStatus !== "connected" ||
    !input.reachable ||
    !input.agentsReady ||
    !input.routeReady
  ) {
    return "wait";
  }
  if (input.pending.gateway && input.pending.gateway !== input.currentGateway) {
    return "discard";
  }
  // The agent screen the user left is still mounted after a background; pushing it again
  // would stack a second copy over it.
  if (input.pending.agent === input.viewingAgent) {
    return "discard";
  }
  return input.agentNames.includes(input.pending.agent) ? "open" : "discard";
}
