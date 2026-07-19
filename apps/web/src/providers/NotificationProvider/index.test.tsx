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
import type { AgentInfo } from "@/lib/types";
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

function agentInfo(name: string, status: AgentInfo["status"]): AgentInfo {
  return { name, status, activityState: "idle", services: {} };
}

function node(status: AgentInfo["status"]) {
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

function tree(statuses: Record<string, AgentInfo["status"]>): Tree {
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

function makeController(statuses: Record<string, AgentInfo["status"]>) {
  const replica = createReplica();
  replica.applySnapshot(tree(statuses));
  const listeners = new Set<(delta: Delta) => void>();
  const controller: Controller = {
    replica,
    http: { request: vi.fn(), json: vi.fn() },
    watch: vi.fn(),
    unwatch: vi.fn(),
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

function gatewayValue(agents: AgentInfo[]): GatewayContextValue {
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
  agents: AgentInfo[],
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
  it("watches every alive agent and unwatches them on unmount", async () => {
    const { controller } = makeController({ ada: "alive", bob: "alive" });
    const view = mount(controller, [
      agentInfo("ada", "alive"),
      agentInfo("bob", "alive"),
    ]);
    await flush();

    expect(vi.mocked(controller.watch).mock.calls.sort()).toEqual([
      ["ada"],
      ["bob"],
    ]);

    view.unmount();
    expect(vi.mocked(controller.unwatch).mock.calls.sort()).toEqual([
      ["ada"],
      ["bob"],
    ]);
  });

  it("does not watch a non-alive agent", async () => {
    const { controller } = makeController({
      ada: "alive",
      bob: "not_authenticated",
    });
    mount(controller, [
      agentInfo("ada", "alive"),
      agentInfo("bob", "not_authenticated"),
    ]);
    await flush();

    expect(vi.mocked(controller.watch).mock.calls).toEqual([["ada"]]);
  });

  it("fires one background chat preview for a non-active agent when unfocused", async () => {
    const { controller, emit } = makeController({ ada: "alive", bob: "alive" });
    mount(controller, [agentInfo("ada", "alive"), agentInfo("bob", "alive")]);
    await flush();
    blur();

    act(() => {
      emit({
        type: "append",
        agent: "bob",
        events: [{ type: "chat", text: "pong", id: 1 }],
      });
    });

    expect(built).toEqual([{ title: "bob", body: "pong" }]);
  });

  it("defers the actively-chatted agent's chat preview to the chat surface", async () => {
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
        type: "append",
        agent: "ada",
        events: [{ type: "chat", text: "hi", id: 2 }],
      });
    });

    expect(built).toEqual([]);
  });

  it("fires a rate-limit alert even while focused", async () => {
    const { controller, emit } = makeController({ ada: "alive" });
    mount(controller, [agentInfo("ada", "alive")]);
    await flush();

    act(() => {
      emit({
        type: "append",
        agent: "ada",
        events: [
          {
            type: "rate_limited",
            text: "resets at 3pm",
            id: 3,
            window: null,
            resets_at: null,
          },
        ],
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
            summary: '<notification source="whatsapp">hey</notification>',
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
