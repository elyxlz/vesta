import { describe, expect, it } from "vitest"
import { parseNotificationContent, type NotificationView } from "./notification-content"

function notification(summary: string, patch: Partial<NotificationView> = {}): NotificationView {
  return {
    type: "notification",
    source: "test",
    summary,
    ...patch,
  }
}

describe("parseNotificationContent", () => {
  // The message channel: a promoted content field as inner body, escaped entities decoded, a
  // routing attribute (chat_name) lifted into context. Mirrors Notification.format_for_display's
  // attribute-plus-content shape.
  it("decodes a message channel and lifts a routing attribute into context", () => {
    expect(
      parseNotificationContent(
        notification(
          '<channel source="whatsapp" type="message" chat_name="Bride &amp; squad">Hi &amp; welcome &lt;3</channel>',
          { notif_type: "message" },
        ),
      ),
    ).toEqual({
      headline: "Hi & welcome <3",
      body: null,
      context: "Bride & squad",
    })
  })

  // The body-prose channel: a multi-line `body` rendered directly as the inner text (core/system
  // notifications), no attributes to promote.
  it("keeps a multi-line body-prose channel as the headline", () => {
    expect(
      parseNotificationContent(
        notification(
          '<channel source="core" type="nightly_dream">\nLine one\nLine two\n</channel>',
          {
            notif_type: "nightly_dream",
          },
        ),
      ),
    ).toEqual({
      headline: "Line one\nLine two",
      body: null,
      context: null,
    })
  })

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
    })
  })

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
    })
  })

  it("keeps an unknown legacy summary as a safe fallback", () => {
    expect(parseNotificationContent(notification("Legacy notification"))).toEqual({
      headline: "Legacy notification",
      body: null,
      context: null,
    })
  })
})
