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

// A fake AgentSocket context: `pending` is the connect-snapshot seed; `messages` carries any live
// notification / notification_cleared deltas the card folds on top of it.
function socketValue(
  messages: VestaEvent[],
  pending: string[] = [],
): AgentSocketValue {
  return {
    messages,
    agentState: "idle",
    isTyping: false,
    connected: true,
    historyLoaded: true,
    pendingNotifications: pending,
    hasMore: false,
    loadingMore: false,
    loadMore: async () => {
      /* noop */
    },
    send: () => true,
    sendEvent: () => true,
    showToolCalls: false,
    setShowToolCalls: () => {
      /* noop */
    },
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
          decided: "snooze",
          ts: new Date().toISOString(),
        },
      ],
      cursor: null,
    });
    render(<NotificationsCard />);

    expect(await screen.findByText("twitter")).toBeTruthy();
    expect(screen.getByText("a new tweet")).toBeTruthy();
    // decided=snooze renders the "snooze" disposition badge.
    expect(screen.getByText("snooze")).toBeTruthy();
  });

  it("renders a trashed notification's disposition", async () => {
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "whatsapp",
          summary:
            '<notification source="whatsapp" type="message">status update</notification>',
          notif_type: "message",
          sender: "someone",
          decided: "trash",
          ts: new Date().toISOString(),
        },
      ],
      cursor: null,
    });
    render(<NotificationsCard />);

    expect(await screen.findByText("whatsapp")).toBeTruthy();
    // decided=trash renders the "trashed" disposition badge.
    expect(screen.getByText("trashed")).toBeTruthy();
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
      cursor: null,
    });
    render(<NotificationsCard />);
    expect(await screen.findByText(/no notifications yet/i)).toBeTruthy();
  });
});

describe("NotificationsCard pending", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("marks pending from the snapshot seed: ids in the seed get the dot, others don't", async () => {
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
      cursor: null,
    });
    render(
      // Snapshot seed says only n-pending is still on disk.
      <AgentSocketContext.Provider value={socketValue([], ["n-pending"])}>
        <NotificationsCard />
      </AgentSocketContext.Provider>,
    );
    await screen.findByText("twitter");

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
          decided: "interrupt",
          ts: new Date().toISOString(),
        },
      ],
      cursor: null,
    });
    // Seeded as pending by the snapshot.
    const { rerender } = render(
      <AgentSocketContext.Provider
        value={socketValue([], ["abc-app-chat-message"])}
      >
        <NotificationsCard />
      </AgentSocketContext.Provider>,
    );
    await screen.findByText("app-chat");
    expect(screen.getAllByText("pending")).toHaveLength(1);

    // A live clear for the same id removes it from the pending set.
    rerender(
      <AgentSocketContext.Provider
        value={socketValue(
          [
            {
              type: "notification_cleared",
              notif_id: "abc-app-chat-message",
              ts: new Date().toISOString(),
            },
          ],
          ["abc-app-chat-message"],
        )}
      >
        <NotificationsCard />
      </AgentSocketContext.Provider>,
    );

    await waitFor(() => expect(screen.queryByText("pending")).toBeNull());
  });
});
