import { describe, expect, it, vi } from "vitest";

import { createController } from "./controller";
import {
  REAUTH_POLL_MS,
  TOKEN_REFRESH_BUFFER_MS,
  createSession,
  type ConnectionConfig,
} from "../session/session";
import type { SocketLike } from "../transport/websocket";
import type { Delta } from "../protocol/deltas";
import type { GatewayInfo, Tree } from "../protocol/tree";

class FakeSocket implements SocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((data: string) => void) | null = null;
  onclose: (() => void) | null = null;
  readonly sent: string[] = [];
  closed = false;
  send(data: string | ArrayBuffer): void {
    this.sent.push(typeof data === "string" ? data : "<binary>");
  }
  close(): void {
    this.closed = true;
  }
}

function baseGateway(): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 4111,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
    operation: null,
  };
}

function baseTree(): Tree {
  return { gateway: baseGateway(), agents: {}, devices: [] };
}

const NOW = 1_800_000_000_000;

interface Harness {
  sockets: FakeSocket[];
  timers: { fn: () => void; ms: number }[];
  fetch: ReturnType<typeof vi.fn>;
  controller: ReturnType<typeof createController>;
  expireToken: () => void;
}

// The URL builder is async, so the socket is created a microtask after createController returns.
async function flush(): Promise<void> {
  for (let i = 0; i < 5; i++) await Promise.resolve();
}

async function harness(expiresAt = NOW + 60 * 60 * 1000): Promise<Harness> {
  const sockets: FakeSocket[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  let connection: ConnectionConfig = {
    url: "https://vestad.test",
    accessToken: "tok",
    refreshToken: "ref",
    expiresAt,
  };
  const fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        access_token: "next",
        refresh_token: "ref2",
        expires_in: 3600,
      }),
      { status: 200 },
    ),
  );
  const session = createSession({
    fetch,
    read: () => connection,
    write: (next) => {
      connection = next;
    },
    now: () => NOW,
  });
  const controller = createController({
    session,
    sync: {
      createSocket: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
      setTimer: (fn, ms) => timers.push({ fn, ms }),
      clearTimer: () => undefined,
      clientKind: "web",
    },
  });
  await flush();
  return {
    sockets,
    timers,
    fetch,
    controller,
    expireToken: () => {
      connection = { ...connection, expiresAt: NOW };
    },
  };
}

function hello(version: string, minSupported: string): string {
  return JSON.stringify({
    type: "hello",
    version,
    min_supported: minSupported,
  });
}

describe("createController", () => {
  it("dials the session's token-stamped /sync URL and shares its http client", async () => {
    const h = await harness();
    expect(h.sockets).toHaveLength(1);
    expect(h.controller.http).toBe(h.controller.session.http);
    await h.controller.http.request("/agents");
    expect(h.fetch).toHaveBeenCalledWith(
      "https://vestad.test/agents",
      expect.objectContaining({ headers: expect.any(Headers) as Headers }),
    );
  });

  it("populates the replica from a hello then a snapshot", async () => {
    const h = await harness();
    const socket = h.sockets[0];
    socket?.onopen?.();
    socket?.onmessage?.(hello("0.2.0", "0.0.0"));
    expect(h.controller.replica.getState()).toBeNull();
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }));
    expect(h.controller.replica.getState()?.gateway.port).toBe(4111);
  });

  it("reduces a delta into the replica", async () => {
    const h = await harness();
    const socket = h.sockets[0];
    socket?.onopen?.();
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }));
    const value: GatewayInfo = {
      ...baseGateway(),
      version: "0.3.0",
      updateAvailable: true,
    };
    socket?.onmessage?.(
      JSON.stringify({ type: "state", scope: "gateway", value }),
    );
    expect(h.controller.replica.getState()?.gateway.version).toBe("0.3.0");
    expect(h.controller.replica.getState()?.gateway.updateAvailable).toBe(true);
  });

  it("exposes connection state through getSyncState and subscribeSyncState", async () => {
    const h = await harness();
    const listener = vi.fn();
    h.controller.subscribeSyncState(listener);
    expect(h.controller.getSyncState()).toBe("connecting");
    h.sockets[0]?.onopen?.();
    expect(h.controller.getSyncState()).toBe("open");
    expect(listener).toHaveBeenCalled();
  });

  it("stops notifying sync-state listeners after unsubscribe", async () => {
    const h = await harness();
    const listener = vi.fn();
    const off = h.controller.subscribeSyncState(listener);
    off();
    h.sockets[0]?.onopen?.();
    expect(listener).not.toHaveBeenCalled();
  });

  it("fans out every delta to subscribeDeltas, including the user_notification the reducer ignores", async () => {
    const h = await harness();
    const seen: Delta[] = [];
    h.controller.subscribeDeltas((delta) => seen.push(delta));
    const socket = h.sockets[0];
    socket?.onopen?.();
    socket?.onmessage?.(JSON.stringify({ type: "snapshot", tree: baseTree() }));
    const userNotification: Delta = {
      type: "user_notification",
      id: 1,
      at: 1_700_000_000,
      agent: "scout",
      kind: "message",
      title: "scout",
      body: "hi",
    };
    socket?.onmessage?.(JSON.stringify(userNotification));
    expect(seen).toEqual([userNotification]);
    // The user notification is a transient user-facing delta: it never mutates the tree.
    expect(h.controller.replica.getState()?.agents.scout).toBeUndefined();
  });

  it("stops fanning out deltas after unsubscribe", async () => {
    const h = await harness();
    const seen: Delta[] = [];
    const off = h.controller.subscribeDeltas((delta) => seen.push(delta));
    off();
    const socket = h.sockets[0];
    socket?.onopen?.();
    socket?.onmessage?.(
      JSON.stringify({
        type: "user_notification",
        id: 1,
        at: 1_700_000_000,
        agent: "scout",
        kind: "message",
        title: "scout",
        body: "hi",
      }),
    );
    expect(seen).toEqual([]);
  });

  it("tracks anyFocused from presence deltas", async () => {
    const h = await harness();
    const listener = vi.fn();
    h.controller.subscribeAnyFocused(listener);
    expect(h.controller.getAnyFocused()).toBe(false);
    const socket = h.sockets[0];
    socket?.onopen?.();
    socket?.onmessage?.(
      JSON.stringify({ type: "presence", any_focused: true }),
    );
    expect(h.controller.getAnyFocused()).toBe(true);
    expect(listener).toHaveBeenCalled();
  });

  it("closes the socket and reports the closed state", async () => {
    const h = await harness();
    h.sockets[0]?.onopen?.();
    h.controller.close();
    expect(h.sockets[0]?.closed).toBe(true);
    expect(h.controller.getSyncState()).toBe("closed");
  });

  describe("reauth tick", () => {
    it("leaves a fresh token alone and re-arms the poll", async () => {
      const h = await harness();
      expect(h.fetch).not.toHaveBeenCalled();
      const poll = h.timers.find((timer) => timer.ms === REAUTH_POLL_MS);
      expect(poll).toBeDefined();
    });

    it("refreshes an already-expiring token before the socket dials, so the first URL is live", async () => {
      const h = await harness(NOW + TOKEN_REFRESH_BUFFER_MS - 1);
      await vi.waitFor(() => {
        expect(h.sockets).toHaveLength(1);
      });
      expect(h.fetch).toHaveBeenCalledWith(
        "https://vestad.test/auth/refresh",
        expect.anything(),
      );
      // The dial already carried the fresh token; a reauth frame issued meanwhile carries it too.
      h.sockets[0]?.onopen?.();
      for (const frame of h.sockets[0]?.sent ?? []) {
        if (frame.includes("reauth")) expect(frame).toContain('"token":"next"');
      }
    });

    it("rotates a token that expires mid-session in-band over the open socket on the next poll", async () => {
      const h = await harness();
      const socket = h.sockets[0];
      socket?.onopen?.();
      h.expireToken();
      const poll = h.timers.find((timer) => timer.ms === REAUTH_POLL_MS);
      poll?.fn();
      await vi.waitFor(() => {
        expect(socket?.sent).toContain(
          JSON.stringify({ type: "reauth", token: "next" }),
        );
      });
      expect(
        h.timers.filter((timer) => timer.ms === REAUTH_POLL_MS),
      ).toHaveLength(2);
    });

    it("stops polling once closed", async () => {
      const h = await harness();
      h.controller.close();
      const poll = h.timers.find((timer) => timer.ms === REAUTH_POLL_MS);
      poll?.fn();
      await flush();
      expect(
        h.timers.filter((timer) => timer.ms === REAUTH_POLL_MS),
      ).toHaveLength(1);
    });
  });
});
