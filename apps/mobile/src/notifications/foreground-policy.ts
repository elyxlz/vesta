let visibleAgentSocket: {
  gateway: string;
  agent: string;
  connected: boolean;
} | null = null;

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

export function shouldPresentForegroundNotification(
  data: Record<string, unknown> | null | undefined,
): boolean {
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
}
