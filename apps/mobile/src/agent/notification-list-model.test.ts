import { describe, expect, it } from "vitest";
import type { NotificationEvent } from "@vesta/core";
import { notificationRows } from "./notification-list-model";

function notification(
  id: number,
  summary: string,
  notifId: string,
): NotificationEvent {
  return {
    id,
    type: "notification",
    source: "email",
    summary,
    notif_id: notifId,
    ts: "2026-09-05T09:00:00Z",
  };
}

const STORED = notification(1, "the invoice was paid", "email-1");
const PENDING = notification(2, "the roof is leaking", "email-2");

describe("notification rows", () => {
  it("gives a pending notification the loaded page does not carry a row of its own", () => {
    expect(notificationRows([STORED], [PENDING], false)).toEqual([
      PENDING,
      STORED,
    ]);
  });

  it("leaves the page alone when the pending set names only rows it carries", () => {
    expect(notificationRows([STORED], [STORED], false)).toEqual([STORED]);
  });

  it("reads the merged list oldest first for the bottom-aligned sheet", () => {
    expect(notificationRows([STORED], [PENDING], true)).toEqual([
      STORED,
      PENDING,
    ]);
  });
});
