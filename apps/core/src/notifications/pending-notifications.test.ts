import { describe, expect, it } from "vitest";
import {
  mergePending,
  samePendingNotifications,
} from "./pending-notifications";
import type { NotificationEvent } from "../protocol/events";

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

describe("mergePending", () => {
  it("puts a pending notification the page does not carry above the page", () => {
    expect(mergePending([STORED], [PENDING])).toEqual([PENDING, STORED]);
  });

  it("lists the newest pending arrival first", () => {
    const older = notification(3, "the bin is full", "email-3");
    const newer = notification(4, "the door is open", "email-4");

    expect(mergePending([STORED], [older, newer])).toEqual([
      newer,
      older,
      STORED,
    ]);
  });

  it("hands back the page itself when every pending arrival is already on it", () => {
    const history = [STORED];

    expect(mergePending(history, [STORED])).toBe(history);
  });

  // vestad stubs a pending id it never saw arrive live: same notif_id, no timestamp, no content.
  // That stub names a row the page already shows, so it must not add a second, empty one.
  it("drops a pending stub that names a row the page already shows", () => {
    const stub: NotificationEvent = {
      id: 0,
      type: "notification",
      source: "",
      summary: "",
      notif_id: STORED.notif_id,
    };

    expect(mergePending([STORED], [stub])).toEqual([STORED]);
  });
});

describe("samePendingNotifications", () => {
  it("reads two arrays naming the same arrivals as one set", () => {
    expect(
      samePendingNotifications([STORED, PENDING], [{ ...STORED }, PENDING]),
    ).toBe(true);
  });

  it("reads a changed length or a changed arrival as a new set", () => {
    expect(samePendingNotifications([STORED], [STORED, PENDING])).toBe(false);
    expect(samePendingNotifications([STORED], [PENDING])).toBe(false);
  });
});
