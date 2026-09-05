import { afterEach, describe, expect, it, vi } from "vitest";
import { createReplica, type Room } from "@vesta/core";
import { fakeTree } from "@/test/fake-controller";
import { ROOM_SETTLE_TIMEOUT_MS, waitForRoom } from "./wait-for-room";

const ROOM: Room = {
  id: "grp-1",
  name: "trip",
  agents: ["ada", "nova"],
  createdAt: 1,
  lastMessageAt: null,
};

afterEach(() => {
  vi.useRealTimers();
});

describe("waitForRoom", () => {
  it("resolves at once when the replica already carries the room", async () => {
    const replica = createReplica();
    replica.applySnapshot(fakeTree({ rooms: [ROOM] }));
    await expect(waitForRoom(replica, "grp-1")).resolves.toBeUndefined();
  });

  it("waits for the delta that adds the room", async () => {
    vi.useFakeTimers();
    const replica = createReplica();
    replica.applySnapshot(fakeTree());
    const settled = vi.fn();
    const waiting = waitForRoom(replica, "grp-1").then(settled);

    await vi.advanceTimersByTimeAsync(ROOM_SETTLE_TIMEOUT_MS - 1);
    expect(settled).not.toHaveBeenCalled();

    replica.applyDelta({ type: "rooms", rooms: [ROOM] });
    await waiting;
    expect(settled).toHaveBeenCalled();
  });

  it("gives up once the bound elapses", async () => {
    vi.useFakeTimers();
    const replica = createReplica();
    replica.applySnapshot(fakeTree());
    const settled = vi.fn();
    const waiting = waitForRoom(replica, "grp-1").then(settled);

    await vi.advanceTimersByTimeAsync(ROOM_SETTLE_TIMEOUT_MS);
    await waiting;
    expect(settled).toHaveBeenCalled();
  });
});
