import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { createElement, useEffect, type ReactNode } from "react";
import type { Controller, NotificationEvent, Tree } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import type { AgentRow } from "@/lib/types";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import { fakeController, fakeTree } from "@/test/fake-controller";
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
    operation: null,
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
      operation: null,
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
  return fakeTree({ agents });
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

function setWindowFocus(focused: boolean) {
  act(() => {
    window.dispatchEvent(new Event(focused ? "focus" : "blur"));
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

interface ToastCase {
  name: string;
  kind: string;
  focused: boolean;
  anyFocused?: boolean;
  chatting?: string;
  agent?: string;
  title: string;
  body: string;
  expected: { title: string; body?: string }[];
}

// The one rule this suite pins: which kinds surface an OS notification, and how the client's own focus
// (this window, or any client via anyFocused) and an in-view chat suppress it. `rate_limited` is the
// legacy alias for a needs-user nudge and toasts on the same terms as needs_user.
const toastCases: ToastCase[] = [
  {
    name: "toasts a background chat alert with the server preview when unfocused",
    kind: "message",
    focused: false,
    agent: "ada",
    title: "ada",
    body: "pong",
    expected: [{ title: "ada", body: "pong" }],
  },
  {
    name: "defers the actively-chatted agent's chat alert to the chat surface",
    kind: "message",
    focused: false,
    chatting: "ada",
    agent: "ada",
    title: "ada",
    body: "hi",
    expected: [],
  },
  {
    name: "does not toast a chat alert while focused",
    kind: "message",
    focused: true,
    title: "ada",
    body: "hi",
    expected: [],
  },
  {
    name: "does not toast a chat alert while another client is focused",
    kind: "message",
    focused: false,
    anyFocused: true,
    title: "ada",
    body: "hi",
    expected: [],
  },
  {
    name: "toasts a needs-user alert with the server title even while focused",
    kind: "needs_user",
    focused: true,
    title: "ada needs to be set up",
    body: "Choose a provider and sign in.",
    expected: [
      {
        title: "ada needs to be set up",
        body: "Choose a provider and sign in.",
      },
    ],
  },
  {
    name: "toasts an older gateway's rate-limit alert even while focused",
    kind: "rate_limited",
    focused: true,
    title: "ada",
    body: "resets at 3pm",
    expected: [{ title: "ada", body: "resets at 3pm" }],
  },
  {
    name: "announces a gateway update with the gateway's chosen title when blurred",
    kind: "gateway_updated",
    focused: false,
    agent: "",
    title: "Updated to v0.1.190",
    body: "Your gateway updated to v0.1.190.",
    expected: [
      {
        title: "Updated to v0.1.190",
        body: "Your gateway updated to v0.1.190.",
      },
    ],
  },
  {
    name: "does not announce a gateway update to a focused client",
    kind: "gateway_updated",
    focused: true,
    agent: "",
    title: "Updated to v0.1.190",
    body: "Your gateway updated to v0.1.190.",
    expected: [],
  },
];

describe("NotificationProvider", () => {
  it.each(toastCases)("$name", async (row) => {
    const agent = row.agent ?? "ada";
    const { controller, emit } = fakeController(tree({ ada: "alive" }), {
      anyFocused: row.anyFocused ?? false,
    });
    mount(
      controller,
      [agentInfo("ada", "alive")],
      row.chatting
        ? createElement(ChattingWith, { agent: row.chatting })
        : null,
    );
    await flush();
    setWindowFocus(row.focused);

    act(() => {
      emit({
        type: "user_notification",
        id: 1,
        at: 1_700_000_000,
        agent,
        kind: row.kind,
        title: row.title,
        body: row.body,
      });
    });

    expect(built).toEqual(row.expected);
  });

  it("lights the unseen badge when the fleet's pending count grows while hidden", async () => {
    const { controller, emit } = fakeController(tree({ ada: "alive" }));
    mount(controller, [agentInfo("ada", "alive")]);
    await flush();
    setHidden(true);

    act(() => {
      emit({
        type: "agent_notifications",
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
