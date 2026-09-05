import { pushRoom } from "./notification-routing";

let visibleRoomSocket: {
  gateway: string;
  roomId: string;
  connected: boolean;
} | null = null;
let syncConnected = false;

export function setVisibleRoomSocket(
  gateway: string,
  roomId: string,
  connected: boolean,
): () => void {
  visibleRoomSocket = roomId ? { gateway, roomId, connected } : null;
  return () => {
    if (visibleRoomSocket?.roomId === roomId) visibleRoomSocket = null;
  };
}

// The conversation on screen, or null. UserNotifications defers a foreground user notification for
// this room (its chat already shows the message).
export function activeRoomId(): string | null {
  return visibleRoomSocket?.roomId ?? null;
}

export function setSyncConnected(connected: boolean): void {
  syncConnected = connected;
}

export function shouldPresentForegroundNotification(
  data: Record<string, unknown> | null | undefined,
): boolean {
  // While /sync is connected the `user_notification` delta is the single owner of foreground
  // presentation; suppressing the Expo push here prevents a double-notify. When sync is down, the push
  // is the fallback and the visible-room suppression (a subset) still applies.
  if (syncConnected) return false;
  const agent = typeof data?.agent === "string" ? data.agent : "";
  const gateway = typeof data?.gateway === "string" ? data.gateway : null;
  // Gateway-owned news names no agent, so it belongs to no conversation and nothing defers it.
  if (!agent) return true;
  const room = pushRoom(data?.route, agent);
  return !(
    visibleRoomSocket?.roomId === room &&
    (!gateway || visibleRoomSocket.gateway === gateway) &&
    visibleRoomSocket.connected
  );
}

export function resetForegroundNotificationPolicyForTests(): void {
  visibleRoomSocket = null;
  syncConnected = false;
}
