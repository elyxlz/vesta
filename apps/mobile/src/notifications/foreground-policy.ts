let visibleAgentSocket: {
  gateway: string;
  agent: string;
  connected: boolean;
} | null = null;
let syncConnected = false;

export function setVisibleAgentSocket(
  gateway: string,
  agent: string,
  connected: boolean,
): () => void {
  visibleAgentSocket = agent ? { gateway, agent, connected } : null;
  return () => {
    if (visibleAgentSocket?.agent === agent) visibleAgentSocket = null;
  };
}

// The agent whose chat is on screen, or null. AlertNotifications defers a foreground alert for
// this agent (its chat already shows the message).
export function activeAgentName(): string | null {
  return visibleAgentSocket?.agent ?? null;
}

export function setSyncConnected(connected: boolean): void {
  syncConnected = connected;
}

export function shouldPresentForegroundNotification(
  data: Record<string, unknown> | null | undefined,
): boolean {
  // While /sync is connected the `alert` delta is the single owner of foreground presentation;
  // suppressing the Expo push here prevents a double-notify. When sync is down, the push is the
  // fallback and the visible-agent suppression (a subset) still applies.
  if (syncConnected) return false;
  const agent = typeof data?.agent === "string" ? data.agent : null;
  const gateway = typeof data?.gateway === "string" ? data.gateway : null;
  return !(
    agent &&
    visibleAgentSocket?.agent === agent &&
    (!gateway || visibleAgentSocket.gateway === gateway) &&
    visibleAgentSocket.connected
  );
}

export function resetForegroundNotificationPolicyForTests(): void {
  visibleAgentSocket = null;
  syncConnected = false;
}
