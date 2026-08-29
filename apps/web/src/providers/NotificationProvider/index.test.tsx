import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import { createElement, useEffect, type ReactNode } from "react";
import type { Controller, NotificationEvent, Tree } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { setAppBadge } from "@/lib/app-badge";
import { setFaviconUnseen } from "@/lib/favicon";
import {
  fakeAgentNode,
  fakeController,
  fakeTree,
} from "@/test/fake-controller";
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
const built: FakeNotification[] = [];
class FakeNotification {
  static permission: NotificationPermission = "granted";
  static requestPermission = vi.fn((): Promise<NotificationPermission> =>
    Promise.resolve("granted"),
  );
  readonly title: string;
  readonly body: string | undefined;
  onclick: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close(): void {
    /* noop */
  }
  constructor(title: string, options?: NotificationOptions) {
    this.title = title;
    this.body = options?.body;
    built.push(this);
  }
}

const ASKED_KEY = "vesta-notifications-asked";

function tree(pending: NotificationEvent[] = []): Tree {
  return fakeTree({ agents: { ada: fakeAgentNode({}, pending) } });
}

function toasts(): { title: string; body?: string }[] {
  return built.map(({ title, body }) => ({ title, body }));
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
  child: ReactNode = null,
  onOpenAgent: (agent: string) => void = () => undefined,
) {
  return render(
    createElement(
      ControllerContext.Provider,
      { value: controller },
      createElement(NotificationProvider, { onOpenAgent, children: child }),
    ),
  );
}

// Let the async permission probe settle, however many awaits it takes: a macrotask boundary drains
// every pending microtask.
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
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

function pendingNotification(id: number): NotificationEvent {
  return {
    type: "notification",
    source: "whatsapp",
    summary: '<channel source="whatsapp">hey</channel>',
    notif_id: `n-${String(id)}`,
    id,
  };
}

function userNotification(
  kind: string,
  fields: { agent?: string; title?: string; body?: string } = {},
) {
  return {
    type: "user_notification" as const,
    id: 1,
    at: 1_700_000_000,
    agent: fields.agent ?? "ada",
    kind,
    title: fields.title ?? "ada",
    body: fields.body ?? "hi",
  };
}

beforeEach(() => {
  built.length = 0;
  setAppBadgeMock.mockClear();
  setFaviconUnseenMock.mockClear();
  FakeNotification.requestPermission.mockClear();
  vi.stubGlobal("Notification", FakeNotification);
  FakeNotification.permission = "granted";
  localStorage.clear();
  setHidden(false);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  // `hidden` lives on Document.prototype; the own override must not leak into other suites.
  Reflect.deleteProperty(document, "hidden");
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
    title: "ada",
    body: "pong",
    expected: [{ title: "ada", body: "pong" }],
  },
  {
    name: "defers the actively-chatted agent's chat alert to the chat surface",
    kind: "message",
    focused: false,
    chatting: "ada",
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
    name: "skips a chat alert whose preview is blank",
    kind: "message",
    focused: false,
    title: "ada",
    body: "   ",
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
    const { controller, emit } = fakeController(tree(), {
      anyFocused: row.anyFocused ?? false,
    });
    mount(
      controller,
      row.chatting
        ? createElement(ChattingWith, { agent: row.chatting })
        : null,
    );
    await settle();
    setWindowFocus(row.focused);

    act(() => {
      emit(userNotification(row.kind, row));
    });

    expect(toasts()).toEqual(row.expected);
  });

  // The OS permission gates every toast: denied is final, and an undecided permission is asked for
  // exactly once per install, so a dismissed prompt never nags on every launch.
  it.each<{
    name: string;
    permission: NotificationPermission;
    asked: boolean;
    prompts: number;
    toasts: number;
    marked: string | null;
  }>([
    {
      name: "denied permission",
      permission: "denied",
      asked: false,
      prompts: 0,
      toasts: 0,
      marked: null,
    },
    {
      name: "undecided, never asked",
      permission: "default",
      asked: false,
      prompts: 1,
      toasts: 1,
      marked: "1",
    },
    {
      name: "undecided, already asked",
      permission: "default",
      asked: true,
      prompts: 0,
      toasts: 0,
      marked: "1",
    },
  ])("$name: prompts $prompts time(s) and toasts $toasts", async (row) => {
    FakeNotification.permission = row.permission;
    if (row.asked) localStorage.setItem(ASKED_KEY, "1");
    const { controller, emit } = fakeController(tree());
    mount(controller);
    await settle();
    setWindowFocus(false);

    act(() => {
      emit(userNotification("message"));
    });

    expect(FakeNotification.requestPermission).toHaveBeenCalledTimes(
      row.prompts,
    );
    expect(built).toHaveLength(row.toasts);
    expect(localStorage.getItem(ASKED_KEY)).toBe(row.marked);
  });

  // A toast is the one way an OS notification reaches its agent: tapping it opens that agent's page.
  it("opens the agent when its toast is clicked", async () => {
    const onOpenAgent = vi.fn();
    const { controller, emit } = fakeController(tree());
    mount(controller, null, onOpenAgent);
    await settle();
    setWindowFocus(false);
    act(() => {
      emit(userNotification("message", { agent: "ada", body: "pong" }));
    });

    act(() => {
      built[0]?.onclick?.();
    });

    await waitFor(() => {
      expect(onOpenAgent).toHaveBeenCalledWith("ada");
    });
  });

  // The fleet-wide pending count is the replica's truth for unprocessed notifications: a rise while
  // hidden lights the unseen badge, a fall never does, and coming back to a visible window clears it.
  it("lights the unseen badge when the fleet's pending count grows while hidden", async () => {
    const { controller, emit } = fakeController(tree());
    mount(controller);
    await settle();
    setHidden(true);

    act(() => {
      emit({
        type: "agent_notifications",
        agent: "ada",
        pending: [pendingNotification(4)],
      });
    });

    expect(setAppBadgeMock).toHaveBeenCalledWith(true);
    expect(setFaviconUnseenMock).toHaveBeenCalledWith(true);
  });

  it("does not light the unseen badge when the pending count falls", async () => {
    const { controller, emit } = fakeController(
      tree([pendingNotification(4), pendingNotification(5)]),
    );
    mount(controller);
    await settle();
    setHidden(true);

    act(() => {
      emit({ type: "agent_notifications", agent: "ada", pending: [] });
    });

    expect(setAppBadgeMock).not.toHaveBeenCalledWith(true);
    expect(setFaviconUnseenMock).not.toHaveBeenCalledWith(true);
  });

  it("clears the unseen badge when the window becomes visible again", async () => {
    const { controller, emit } = fakeController(tree());
    mount(controller);
    await settle();
    setHidden(true);
    act(() => {
      emit({
        type: "agent_notifications",
        agent: "ada",
        pending: [pendingNotification(4)],
      });
    });
    setAppBadgeMock.mockClear();
    setFaviconUnseenMock.mockClear();

    setHidden(false);
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(setAppBadgeMock).toHaveBeenCalledWith(false);
    expect(setFaviconUnseenMock).toHaveBeenCalledWith(false);
  });
});
