import { describe, expect, it } from "vitest";

import { parseServerFrame } from "./parse";

describe("parseServerFrame", () => {
  it("parses a hello frame, mapping min_supported off the wire", () => {
    const parsed = parseServerFrame(
      JSON.stringify({
        type: "hello",
        version: "0.2.0",
        min_supported: "0.0.0",
      }),
    );
    expect(parsed).toEqual({
      kind: "hello",
      frame: { type: "hello", version: "0.2.0", minSupported: "0.0.0" },
    });
  });

  it("ignores a hello frame missing its version window", () => {
    expect(
      parseServerFrame(JSON.stringify({ type: "hello", version: "0.2.0" })),
    ).toEqual({
      kind: "unknown",
    });
  });

  it("parses a snapshot frame and preserves the tree", () => {
    const tree = { gateway: {}, agents: {} };
    const parsed = parseServerFrame(JSON.stringify({ type: "snapshot", tree }));
    expect(parsed.kind).toBe("snapshot");
    if (parsed.kind === "snapshot") expect(parsed.frame.tree).toEqual(tree);
  });

  it("classifies each delta type", () => {
    const cases: { raw: Record<string, unknown>; type: string }[] = [
      {
        raw: { type: "state", scope: "gateway", value: { version: "1" } },
        type: "state",
      },
      {
        raw: { type: "agent", name: "scout", info: { status: "alive" } },
        type: "agent",
      },
      { raw: { type: "agent_removed", name: "scout" }, type: "agent_removed" },
      {
        raw: { type: "agent_notifications", agent: "scout", pending: [] },
        type: "agent_notifications",
      },
      {
        raw: {
          type: "user_notification",
          id: 1,
          at: 1_700_000_000,
          agent: "scout",
          kind: "message",
          title: "scout",
          body: "hi",
        },
        type: "user_notification",
      },
    ];
    for (const entry of cases) {
      const parsed = parseServerFrame(JSON.stringify(entry.raw));
      expect(parsed.kind).toBe("delta");
      if (parsed.kind === "delta") expect(parsed.delta.type).toBe(entry.type);
    }
  });

  it("carries the user_notification log identity, agent, kind, title, and body through", () => {
    const parsed = parseServerFrame(
      JSON.stringify({
        type: "user_notification",
        id: 12,
        at: 1_700_000_000,
        agent: "scout",
        kind: "message",
        title: "scout",
        body: "hello there",
      }),
    );
    expect(parsed.kind).toBe("delta");
    if (parsed.kind === "delta" && parsed.delta.type === "user_notification") {
      expect(parsed.delta.id).toBe(12);
      expect(parsed.delta.at).toBe(1_700_000_000);
      expect(parsed.delta.agent).toBe("scout");
      expect(parsed.delta.kind).toBe("message");
      expect(parsed.delta.title).toBe("scout");
      expect(parsed.delta.body).toBe("hello there");
    }
  });

  it("carries the gateway's own update announcement, which names no agent", () => {
    const parsed = parseServerFrame(
      JSON.stringify({
        type: "user_notification",
        id: 4,
        at: 1_700_000_000,
        agent: "",
        kind: "gateway_updated",
        title: "Updated to v0.1.190",
        body: "Your gateway updated to v0.1.190.",
      }),
    );
    expect(parsed).toEqual({
      kind: "delta",
      delta: {
        type: "user_notification",
        id: 4,
        at: 1_700_000_000,
        agent: "",
        kind: "gateway_updated",
        title: "Updated to v0.1.190",
        body: "Your gateway updated to v0.1.190.",
      },
    });
  });

  it("ignores a user_notification missing its log identity, kind, title, or body", () => {
    const whole = {
      type: "user_notification",
      id: 1,
      at: 1_700_000_000,
      agent: "scout",
      kind: "message",
      title: "scout",
      body: "hi",
    };
    const inputs = ["id", "at", "kind", "title", "body"].map((missing) =>
      JSON.stringify(
        Object.fromEntries(
          Object.entries(whole).filter(([key]) => key !== missing),
        ),
      ),
    );
    for (const raw of inputs)
      expect(parseServerFrame(raw)).toEqual({ kind: "unknown" });
  });

  it("parses a presence frame", () => {
    const parsed = parseServerFrame(
      JSON.stringify({ type: "presence", any_focused: true }),
    );
    expect(parsed).toEqual({
      kind: "delta",
      delta: { type: "presence", anyFocused: true },
    });
  });

  it("treats a presence frame without any_focused as unknown", () => {
    expect(parseServerFrame(JSON.stringify({ type: "presence" }))).toEqual({
      kind: "unknown",
    });
  });

  it("parses a devices delta", () => {
    const device = {
      id: "dev-1",
      kind: "desktop",
      descriptor: "Vesta Desktop on macOS",
      present: true,
      lastSeen: "2026-01-01T00:00:00Z",
      pushEnabled: false,
      timezone: "Europe/London",
      position: {
        latitude: 51.5074,
        longitude: -0.1278,
        accuracyM: 50,
        place: { city: "London", region: "England", country: "United Kingdom" },
      },
      positionAt: "2026-01-01T00:00:00Z",
    };
    const parsed = parseServerFrame(
      JSON.stringify({ type: "devices", devices: [device] }),
    );
    expect(parsed).toEqual({
      kind: "delta",
      delta: { type: "devices", devices: [device] },
    });
  });

  it("accepts a device with a null descriptor", () => {
    const device = {
      id: "dev-1",
      kind: "unknown",
      descriptor: null,
      present: false,
      lastSeen: "2026-01-01T00:00:00Z",
      pushEnabled: true,
      timezone: null,
      position: null,
      positionAt: null,
    };
    const parsed = parseServerFrame(
      JSON.stringify({ type: "devices", devices: [device] }),
    );
    expect(parsed).toEqual({
      kind: "delta",
      delta: { type: "devices", devices: [device] },
    });
  });

  it("defaults absent context fields to null and rejects malformed ones", () => {
    const base = {
      id: "dev-1",
      kind: "web",
      descriptor: "Chrome",
      present: true,
      lastSeen: "2026-01-01T00:00:00Z",
      pushEnabled: false,
    };
    expect(
      parseServerFrame(JSON.stringify({ type: "devices", devices: [base] })),
    ).toEqual({
      kind: "delta",
      delta: {
        type: "devices",
        devices: [
          { ...base, timezone: null, position: null, positionAt: null },
        ],
      },
    });
    for (const bad of [
      { ...base, timezone: 42 },
      { ...base, position: { latitude: "x", longitude: 1 } },
      { ...base, position: { latitude: 1, longitude: 1, place: { city: 3 } } },
    ]) {
      expect(
        parseServerFrame(JSON.stringify({ type: "devices", devices: [bad] })),
      ).toEqual({
        kind: "unknown",
      });
    }
  });

  it("fills a position's optional parts with null", () => {
    const device = {
      id: "dev-1",
      kind: "mobile",
      descriptor: "Vesta Mobile on iOS",
      present: true,
      lastSeen: "2026-01-01T00:00:00Z",
      pushEnabled: true,
      position: { latitude: 1.5, longitude: 2.5, place: { city: "Tokyo" } },
    };
    const parsed = parseServerFrame(
      JSON.stringify({ type: "devices", devices: [device] }),
    );
    expect(parsed).toMatchObject({
      delta: {
        devices: [
          {
            position: {
              latitude: 1.5,
              longitude: 2.5,
              accuracyM: null,
              place: { city: "Tokyo", region: null, country: null },
            },
          },
        ],
      },
    });
  });

  it("treats a devices delta with a malformed entry as unknown", () => {
    const bad = {
      id: "dev-1",
      kind: "desktop",
      present: true,
      pushEnabled: false,
    }; // no lastSeen
    expect(
      parseServerFrame(JSON.stringify({ type: "devices", devices: [bad] })),
    ).toEqual({
      kind: "unknown",
    });
  });

  it("ignores unknown frame and delta types", () => {
    const inputs = [
      JSON.stringify({ type: "future_frame", data: 1 }),
      JSON.stringify({ type: "future_delta", agent: "scout" }),
    ];
    for (const raw of inputs)
      expect(parseServerFrame(raw)).toEqual({ kind: "unknown" });
  });

  it("ignores malformed input", () => {
    const inputs = [
      "not json",
      "null",
      "123",
      JSON.stringify({ noType: true }),
    ];
    for (const raw of inputs)
      expect(parseServerFrame(raw)).toEqual({ kind: "unknown" });
  });

  it("ignores a delta missing a required field", () => {
    const inputs = [
      JSON.stringify({ type: "agent", name: "scout" }),
      JSON.stringify({ type: "agent_notifications", agent: "scout" }),
      JSON.stringify({ type: "state", scope: "other", value: {} }),
    ];
    for (const raw of inputs)
      expect(parseServerFrame(raw)).toEqual({ kind: "unknown" });
  });
});
