import { selectRooms, type Controller } from "@vesta/core";

// How long a fresh room gets to reach the replica before the dialog opens it anyway. The node
// answers the create before /sync carries the room, and the room route resolves off the tree, so
// opening on the ack alone races the delta; a silent socket must not trap the dialog either.
export const ROOM_SETTLE_TIMEOUT_MS = 4000;

export function waitForRoom(
  replica: Controller["replica"],
  roomId: string,
  timeoutMs: number = ROOM_SETTLE_TIMEOUT_MS,
): Promise<void> {
  const carriesRoom = (): boolean =>
    selectRooms(replica.getState()).some((room) => room.id === roomId);
  if (carriesRoom()) return Promise.resolve();
  return new Promise<void>((resolve) => {
    let unsubscribe: () => void = () => undefined;
    const settle = (): void => {
      clearTimeout(timer);
      unsubscribe();
      resolve();
    };
    const timer = setTimeout(settle, timeoutMs);
    unsubscribe = replica.subscribe(() => {
      if (carriesRoom()) settle();
    });
  });
}
