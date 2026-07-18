import { describe, expect, it } from "vitest";
import type { NotificationEvent, VestaEvent } from "../api/types";
import {
  getPendingNotificationIds,
  mergeLiveNotifications,
} from "./notification-list-model";

function notification(
  notifId: string,
  ts: string,
): NotificationEvent {
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

  it("combines the snapshot seed with live arrivals and clears", () => {
    const events: VestaEvent[] = [
      notification("new", "2026-01-01T00:01:00Z"),
      { type: "notification_cleared", notif_id: "seed" },
    ];

    expect([...getPendingNotificationIds(["seed"], events)]).toEqual(["new"]);
  });
});
