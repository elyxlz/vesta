import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { createElement, useEffect, type ReactNode } from "react";
import { createReplica } from "@vesta/core";
import type { Controller, Delta, NotificationEvent, Tree } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import type { AgentRow } from "@/lib/types";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { NotificationProvider, useNotifications } from "./index";

vi.mock("@/lib/native", () => ({
  native: {
    focusWindow: vi.fn().mockResolvedValue(undefined),
    onWindowFocusChange: () => () => undefined,
  },
}));
vi.mock("@/lib/app-badge", () => ({ setAppBadge: vi.fn() }));
vi.mock("@/lib/favicon", () => ({ setFaviconUnseen: vi.fn() }));

const setAppBadgeMock = vi.mocked(setAppBadge);
const setFaviconUnseenMock = vi.mocked(setFaviconUnseen);

// A fake OS Notification that records each construction, so the provider's OS-notification firing is
// observable without a real browser.
const built: { title: string; body?: string }[] = [];
class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn((): Promise<NotificationPermission> =>
    Promise.resolve("granted"),
  );
  onclick: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close(): void {
    /* noop */
  }
  constructor(title: string, options?: NotificationOptions) {
    built.push({ title, body: options?.body });
  }
}

function agentInfo(name: string, status: AgentRow["status"]): AgentRow {
  return {
    name,
    status,
    activityState: "idle",
    buildPhase: null,
    startedAt: null,
    services: {},
  };
}

function node(status: AgentRow["status"]) {
  return {
    info: {
      status,
      activityState: "idle" as const,
      buildPhase: null,
      startedAt: null,
      services: {},
    },
    notifications: { pending: [] as NotificationEvent[] },
  };
}

function tree(statuses: Record<string, AgentRow["status"]>): Tree {
  const agents: Tree["agents"] = {};
  for (const [name, status] of Object.entries(statuses))
    agents[name] = node(status);
  return {
    gateway: {
      version: "0.0.0",
      channel: "stable",
      autoUpdate: true,
      port: 7777,
      lan: { exposed: false, url: null },
      tunnelUrl: null,
      updateAvailable: false,
      latestVersion: null,
      managed: false,
    },
    agents,
  };
}

function makeController(statuses: Record<string, AgentRow["status"]>) {
  const replica = createReplica();
  replica.applySnapshot(tree(statuses));
  const listeners = new Set<(delta: Delta) => void>();
  const controller: Controller = {
    replica,
    http: { request: vi.fn(), json: vi.fn() },
    reauth: vi.fn(),
    subscribeDeltas: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    close: () => undefined,
  };
  const emit = (delta: Delta): void => {
    replica.applyDelta(delta);
    for (const listener of listeners) listener(delta);
  };
  return { controller, emit };
}

function gatewayValue(agents: AgentRow[]): GatewayContextValue {
  return { ...disconnectedValue, reachable: true, agents, agentsFetched: true };
}

// Registers the actively-chatted agent through the public useNotifications contract, standing in for
// AgentSocketProvider so the defer-to-active-chat rule can be exercised.
function ChattingWith({ agent }: { agent: string | null }) {
  const { setChattingAgent } = useNotifications();
  useEffect(() => {
    setChattingAgent(agent);
    return () => setChattingAgent(null);
  }, [agent, setChattingAgent]);
  return null;
}

function mount(
  controller: Controller,
  agents: AgentRow[],
  child: ReactNode = null,
) {
  return render(
    createElement(
      GatewayContext.Provider,
      { value: gatewayValue(agents) },
      createElement(
        ControllerContext.Provider,
        { value: controller },
        createElement(NotificationProvider, {
          onOpenAgent: () => undefined,
          children: child,
        }),
      ),
    ),
  );
}

// Flush the async permission probe so permissionRef settles to granted before deltas arrive.
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function blur() {
  act(() => {
    window.dispatchEvent(new Event("blur"));
  });
}

function focus() {
  act(() => {
    window.dispatchEvent(new Event("focus"));
  });
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => hidden,
  });
}

beforeEach(() => {
  built.length = 0;
  setAppBadgeMock.mockClear();
  setFaviconUnseenMock.mockClear();
  vi.stubGlobal("Notification", FakeNotification);
  FakeNotification.permission = "granted";
  localStorage.clear();
  setHidden(false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("NotificationProvider", () => {
  it("toasts a background chat alert with the server preview when unfocused", async () => {
    const { controller, emit } = makeController({ ada: "alive", bob: "alive" });
    mount(controller, [agentInfo("ada", "alive"), agentInfo("bob", "alive")]);
    await flush();
    blur();

    act(() => {
      emit({
        type: "alert",
        agent: "bob",
        kind: "message",
        title: "bob",
        body: "pong",
      });
    });

    expect(built).toEqual([{ title: "bob", body: "pong" }]);
  });

  it("defers the actively-chatted agent's chat alert to the chat surface", async () => {
    const { controller, emit } = makeController({ ada: "alive" });
    mount(
      controller,
      [agentInfo("ada", "alive")],
      createElement(ChattingWith, { agent: "ada" }),
    );
    await flush();
    blur();

    act(() => {
      emit({
        type: "alert",
        agent: "ada",
        kind: "message",
        title: "ada",
        body: "hi",
      });
    });

    expect(built).toEqual([]);
  });

  it("does not toast a background chat alert while focused", async () => {
    const { controller, emit } = makeController({ ada: "alive" });
    mount(controller, [agentInfo("ada", "alive")]);
    await flush();
    focus();

    act(() => {
      emit({
        type: "alert",
        agent: "ada",
        kind: "message",
        title: "ada",
        body: "hi",
      });
    });

    expect(built).toEqual([]);
  });

  it("toasts a rate-limit alert even while focused", async () => {
    const { controller, emit } = makeController({ ada: "alive" });
    mount(controller, [agentInfo("ada", "alive")]);
    await flush();
    focus();

    act(() => {
      emit({
        type: "alert",
        agent: "ada",
        kind: "rate_limited",
        title: "ada",
        body: "resets at 3pm",
      });
    });

    expect(built).toEqual([
      { title: "ada hit a Claude rate limit", body: "resets at 3pm" },
    ]);
  });

  it("lights the unseen badge when the fleet's pending count grows while hidden", async () => {
    const { controller, emit } = makeController({ ada: "alive" });
    mount(controller, [agentInfo("ada", "alive")]);
    await flush();
    setHidden(true);

    act(() => {
      emit({
        type: "notifications",
        agent: "ada",
        pending: [
          {
            type: "notification",
            source: "whatsapp",
            summary: '<channel source="whatsapp">hey</channel>',
            notif_id: "n-1",
            id: 4,
          },
        ],
      });
    });

    expect(setAppBadgeMock).toHaveBeenCalledWith(true);
    expect(setFaviconUnseenMock).toHaveBeenCalledWith(true);
  });
});
