import { describe, expect, it } from "vitest";
import type { NotificationEvent } from "../api/types";
import { parseNotificationContent } from "./notification-content";

function notification(
  summary: string,
  patch: Partial<NotificationEvent> = {},
): NotificationEvent {
  return {
    type: "notification",
    source: "test",
    summary,
    ...patch,
  };
}

describe("notification content", () => {
  it("extracts and decodes a channel message", () => {
    expect(
      parseNotificationContent(
        notification(
          '<channel source="whatsapp" type="message">Hi &amp; welcome</channel>',
          { notif_type: "message" },
        ),
      ),
    ).toEqual({
      headline: "Hi & welcome",
      body: null,
      context: null,
    });
  });

  it("separates an email subject, preview, and account context", () => {
    expect(
      parseNotificationContent(
        notification(
          '<channel source="microsoft" type="email" subject="Launch" preview="Ready to ship" account="work@example.com"></channel>',
          {
            notif_type: "email",
            fields: {
              subject: "Launch",
              preview: "Ready to ship",
              account: "work@example.com",
              folder: "Inbox",
            },
          },
        ),
      ),
    ).toEqual({
      headline: "Launch",
      body: "Ready to ship",
      context: "work@example.com · Inbox",
    });
  });

  it("uses useful structured calendar context", () => {
    expect(
      parseNotificationContent(
        notification('<channel source="microsoft" type="calendar"></channel>', {
          notif_type: "calendar",
          fields: {
            subject: "Design review",
            location: "Studio",
            minutes_until: "15",
          },
        }),
      ),
    ).toEqual({
      headline: "Design review",
      body: null,
      context: "Studio · 15 min",
    });
  });

  it("keeps an unknown legacy summary as a safe fallback", () => {
    expect(parseNotificationContent(notification("Legacy notification"))).toEqual({
      headline: "Legacy notification",
      body: null,
      context: null,
    });
  });
});
