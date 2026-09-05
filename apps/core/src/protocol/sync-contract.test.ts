import { describe, expect, it } from "vitest";

import { syncProtocolFixtures as fixtures } from "../../fixtures/sync-protocol";
import { parseServerFrame } from "./parse";
import type { AgentInfo, GatewayInfo, Room, Tree } from "./tree";

// The generated fixture is `as const`, so its arrays are readonly tuples; the compile-time
// check compares against the readonly view of the canonical types.
type DeepReadonly<T> = T extends (infer U)[]
  ? readonly DeepReadonly<U>[]
  : T extends object
    ? { readonly [K in keyof T]: DeepReadonly<T[K]> }
    : T;

// The fixtures are produced by vestad's real serde path (vestad/src/sync/protocol.rs,
// REGEN_API_FIXTURES=1). Parsing every one with the canonical types proves the Rust->TS seam at
// runtime, and the `satisfies` checks prove it at compile time: a renamed field in either the Rust
// struct or the TypeScript type fails `npm run check` before it can reach a client.
describe("sync protocol contract (vestad fixtures)", () => {
  it("types the snapshot tree, the gateway state, and the agent info at compile time", () => {
    const tree = fixtures.snapshot.tree satisfies DeepReadonly<Tree>;
    const gateway = fixtures.deltas.state
      .value satisfies DeepReadonly<GatewayInfo>;
    const info = fixtures.deltas.agent.info satisfies DeepReadonly<AgentInfo>;
    expect(tree.gateway.port).toBe(4111);
    expect(gateway.latestVersion).toBe("0.1.1");
    expect(info.status).toBe("alive");
  });

  it("types the room list the tree and the rooms delta carry", () => {
    const rooms = fixtures.snapshot.tree.rooms satisfies DeepReadonly<Room[]>;
    expect(rooms[0].id).toBe("dm:sample");
    expect(rooms[0].name).toBeNull();
    expect(rooms[1].agents).toEqual(["sample", "scout"]);
    expect(rooms[1].lastMessageAt).toBeNull();
    const delta = fixtures.deltas.rooms.rooms satisfies DeepReadonly<Room[]>;
    expect(delta).toHaveLength(2);
  });

  it("parses the hello frame vestad emits, carrying the served version window", () => {
    const parsed = parseServerFrame(JSON.stringify(fixtures.hello));
    expect(parsed.kind).toBe("hello");
    if (parsed.kind === "hello") {
      expect(typeof parsed.frame.version).toBe("string");
      expect(parsed.frame.minSupported).toMatch(/^\d+\.\d+\.\d+$/);
    }
  });

  it("parses the snapshot frame and preserves the tree", () => {
    const parsed = parseServerFrame(JSON.stringify(fixtures.snapshot));
    expect(parsed.kind).toBe("snapshot");
    if (parsed.kind === "snapshot") {
      expect(parsed.frame.tree.gateway.autoUpdate).toBe(true);
      expect(parsed.frame.tree.gateway.userNotificationsSeenAt).toBe(
        1_700_000_000,
      );
      expect(parsed.frame.tree.gateway.lastUserNotificationAt).toBe(
        1_700_000_400,
      );
      expect(parsed.frame.tree.agents["sample-agent"]?.info.activityState).toBe(
        "thinking",
      );
    }
  });

  it("classifies every delta vestad emits", () => {
    for (const [type, frame] of Object.entries(fixtures.deltas)) {
      const parsed = parseServerFrame(JSON.stringify(frame));
      expect(parsed.kind).toBe("delta");
      if (parsed.kind === "delta") expect(parsed.delta.type).toBe(type);
    }
  });

  it("carries the log identity, kind, title, and body through the user_notification delta", () => {
    const parsed = parseServerFrame(
      JSON.stringify(fixtures.deltas.user_notification),
    );
    expect(parsed.kind).toBe("delta");
    if (parsed.kind === "delta" && parsed.delta.type === "user_notification") {
      expect(parsed.delta.id).toBe(3);
      expect(parsed.delta.at).toBe(1_700_000_400);
      expect(parsed.delta.agent).toBe("sample-agent");
      expect(parsed.delta.kind).toBe("message");
      expect(parsed.delta.title).toBe("sample-agent");
      expect(parsed.delta.body).toBe("hello");
    }
  });
});
