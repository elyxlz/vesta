import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import { NotificationsCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

describe("NotificationsCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getPendingNotifications").mockResolvedValue([]);
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
      cursor: null,
    });
    render(<NotificationsCard />);

    expect(await screen.findByText("twitter")).toBeTruthy();
    expect(screen.getByText("a new tweet")).toBeTruthy();
    // decided=pool with default interrupt -> "snoozed" + a "by rule" note
    expect(screen.getByText("snoozed")).toBeTruthy();
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

describe("NotificationsCard make-rule", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getPendingNotifications").mockResolvedValue([]);
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
    vi.spyOn(api, "getPendingNotifications").mockResolvedValue(["n-pending"]);
  });
  afterEach(cleanup);

  it("marks a notification pending while its file is still on disk, else cleared", async () => {
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
    render(<NotificationsCard />);
    await screen.findByText("twitter");
    await waitFor(() => expect(api.getPendingNotifications).toHaveBeenCalled());

    expect(await screen.findByText("pending")).toBeTruthy();
    expect(screen.getByText("cleared")).toBeTruthy();
  });
});
