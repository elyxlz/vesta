import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import {
  AgentSocketContext,
  type AgentSocketValue,
} from "@/providers/AgentSocketProvider/context";
import type { VestaEvent } from "@/lib/types";
import { NotificationsCard } from "./index";

function socketValue(messages: VestaEvent[]): AgentSocketValue {
  return {
    messages,
    agentState: "idle",
    isTyping: false,
    connected: true,
    historyLoaded: true,
    hasMore: false,
    loadingMore: false,
    loadMore: () => {},
    send: () => true,
    sendEvent: () => true,
    showToolCalls: false,
    setShowToolCalls: () => {},
  };
}

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

describe("NotificationsCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("renders received notifications with their disposition", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary:
            '<notification source="twitter" type="tweet">a new tweet</notification>',
          notif_type: "tweet",
          sender: "@bob",
          interrupt: true,
          decided: "pool",
          ts: new Date().toISOString(),
        },
      ],
      cleared: [],
      cursor: null,
    });
    render(<NotificationsCard />);

    expect(await screen.findByText("twitter")).toBeTruthy();
    expect(screen.getByText("a new tweet")).toBeTruthy();
    // decided=pool with default interrupt -> "snooze" + a "by rule" note
    expect(screen.getByText("snooze")).toBeTruthy();
    expect(screen.getByText(/by rule/i)).toBeTruthy();
  });

  it("loads older notifications when there's a cursor", async () => {
    const spy = vi
      .spyOn(api, "getNotificationHistory")
      .mockResolvedValueOnce({
        notifications: [
          {
            type: "notification",
            source: "twitter",
            summary:
              '<notification source="twitter" type="tweet">first</notification>',
            notif_type: "tweet",
            ts: new Date().toISOString(),
          },
        ],
        cleared: [],
        cursor: 42,
      })
      .mockResolvedValueOnce({
        notifications: [
          {
            type: "notification",
            source: "email",
            summary:
              '<notification source="email" type="message">older</notification>',
            notif_type: "message",
            ts: new Date().toISOString(),
          },
        ],
        cleared: [],
        cursor: null,
      });
    render(<NotificationsCard />);
    await screen.findByText("twitter");

    await userEvent.click(screen.getByRole("button", { name: /load older/i }));

    await waitFor(() => expect(screen.getByText("email")).toBeTruthy());
    expect(spy).toHaveBeenCalledWith("bob", 42);
  });

  it("shows an empty state when there are none", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cleared: [],
      cursor: null,
    });
    render(<NotificationsCard />);
    expect(await screen.findByText(/no notifications yet/i)).toBeTruthy();
  });
});

describe("NotificationsCard make-rule", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("offers a make-rule action per notification", async () => {
    const onMakeRule = vi.fn();
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary:
            '<notification source="twitter" type="tweet">hi</notification>',
          notif_type: "tweet",
          ts: new Date().toISOString(),
        },
      ],
      cleared: [],
      cursor: null,
    });
    render(<NotificationsCard onMakeRule={onMakeRule} />);
    await screen.findByText("twitter");

    await userEvent.click(screen.getByRole("button", { name: /make a rule/i }));

    expect(onMakeRule).toHaveBeenCalledTimes(1);
    expect(onMakeRule.mock.calls[0][0].source).toBe("twitter");
  });

  it("hides the make-rule action on core notifications", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "core",
          summary:
            '<notification source="core" type="default_skill_sync">synced</notification>',
          notif_type: "default_skill_sync",
          ts: new Date().toISOString(),
        },
      ],
      cleared: [],
      cursor: null,
    });
    render(<NotificationsCard onMakeRule={vi.fn()} />);
    await screen.findByText("core");

    expect(screen.queryByRole("button", { name: /make a rule/i })).toBeNull();
  });
});

describe("NotificationsCard pending/cleared", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("derives pending from the log: an arrival with no matching clear is pending, a cleared one isn't", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary:
            '<notification source="twitter" type="tweet">a</notification>',
          notif_type: "tweet",
          notif_id: "n-pending",
          ts: new Date().toISOString(),
        },
        {
          type: "notification",
          source: "email",
          summary:
            '<notification source="email" type="message">b</notification>',
          notif_type: "message",
          notif_id: "n-cleared",
          ts: new Date().toISOString(),
        },
      ],
      // n-cleared has a matching clear in the log; n-pending does not.
      cleared: ["n-cleared"],
      cursor: null,
    });
    render(<NotificationsCard />);
    await screen.findByText("twitter");

    // Only the row with no clear carries the pending marker.
    expect(await screen.findAllByText("pending")).toHaveLength(1);
  });

  it("clears the pending dot when a notification_cleared arrives live on the socket", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "app-chat",
          summary:
            '<notification source="app-chat" type="message">hi</notification>',
          notif_type: "message",
          notif_id: "abc-app-chat-message",
          interrupt: true,
          decided: "interrupt",
          ts: new Date().toISOString(),
        },
      ],
      cleared: [],
      cursor: null,
    });
    const { rerender } = render(
      <AgentSocketContext.Provider value={socketValue([])}>
        <NotificationsCard />
      </AgentSocketContext.Provider>,
    );
    await screen.findByText("app-chat");
    expect(screen.getAllByText("pending")).toHaveLength(1);

    rerender(
      <AgentSocketContext.Provider
        value={socketValue([
          {
            type: "notification_cleared",
            notif_id: "abc-app-chat-message",
            ts: new Date().toISOString(),
          },
        ])}
      >
        <NotificationsCard />
      </AgentSocketContext.Provider>,
    );

    await waitFor(() => expect(screen.queryByText("pending")).toBeNull());
  });
});
