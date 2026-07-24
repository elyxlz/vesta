export interface PendingNotification {
  identifier: string;
  agent: string;
  eventType: string;
  gateway: string | null;
}

export function pendingNotificationFromData(
  data: Record<string, unknown> | null | undefined,
  identifier: string,
): PendingNotification | null {
  if (!data || typeof data.agent !== "string" || !data.agent.trim()) {
    return null;
  }
  return {
    identifier,
    agent: data.agent.trim(),
    eventType: typeof data.eventType === "string" ? data.eventType : "",
    gateway:
      typeof data.gateway === "string" && data.gateway ? data.gateway : null,
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
  return input.agentNames.includes(input.pending.agent) ? "open" : "discard";
}
