import { describe, expect, it } from "vitest";
import type { ChatMessage, NotificationView } from "@vesta/core";
import {
  getPendingNotificationIds,
  mergeLiveNotifications,
} from "./notification-list-model";

function notification(notifId: string, ts: string): NotificationView {
  return {
    type: "notification",
    source: "test",
    summary: notifId,
    notif_id: notifId,
    ts,
  };
}

describe("notification list model", () => {
  it("prepends live arrivals newest first and deduplicates history", () => {
    const existing = notification("existing", "2026-01-01T00:00:00Z");
    const first = notification("first", "2026-01-01T00:01:00Z");
    const second = notification("second", "2026-01-01T00:02:00Z");

    expect(
      mergeLiveNotifications([existing], [existing, first, second]),
    ).toEqual([second, first, existing]);
  });

  it("surfaces a re-arrival of the same notif_id at a later ts", () => {
    const first = notification(
      "nightly_dream-2026-01-01",
      "2026-01-01T03:00:00Z",
    );
    const redrop = notification(
      "nightly_dream-2026-01-01",
      "2026-01-01T05:00:00Z",
    );

    expect(mergeLiveNotifications([first], [redrop])).toEqual([redrop, first]);
  });

  it("still drops a replay of the same notif_id at the same ts", () => {
    const arrival = notification(
      "nightly_dream-2026-01-01",
      "2026-01-01T03:00:00Z",
    );

    expect(mergeLiveNotifications([arrival], [arrival])).toEqual([arrival]);
  });

  it("keeps two id-less events with the same ts collapsed, as before", () => {
    const older: NotificationView = {
      type: "notification",
      source: "email",
      summary: "a",
      ts: "2026-01-01T00:00:00Z",
    };
    const other: NotificationView = {
      type: "notification",
      source: "twitter",
      summary: "b",
      ts: "2026-01-01T00:00:00Z",
    };

    expect(mergeLiveNotifications([older], [other])).toEqual([older]);
  });

  it("distinguishes id-less, ts-less events by their content", () => {
    const one: NotificationView = {
      type: "notification",
      source: "email",
      summary: "a",
    };
    const two: NotificationView = {
      type: "notification",
      source: "email",
      summary: "b",
    };

    expect(mergeLiveNotifications([one], [two])).toEqual([two, one]);
  });

  it("combines the snapshot seed with live arrivals and clears", () => {
    const events: ChatMessage[] = [
      notification("new", "2026-01-01T00:01:00Z"),
      { type: "notification_cleared", notif_id: "seed" },
    ];

    expect([...getPendingNotificationIds(["seed"], events)]).toEqual(["new"]);
  });
});
