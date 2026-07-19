import { describe, expect, it } from "vitest"

import { isStructured, notificationContent, parseFields } from "./notification-content"

describe("notificationContent", () => {
  it("unwraps the <notification ...>INNER</notification> envelope", () => {
    const summary = `<notification source="sms" type="text">hi there</notification>`
    expect(notificationContent(summary)).toBe("hi there")
  })

  it("returns the raw summary when the envelope is absent or malformed", () => {
    expect(notificationContent("plain body")).toBe("plain body")
    expect(notificationContent("</notification>oops")).toBe("</notification>oops")
  })
})

describe("parseFields", () => {
  it("splits key=value, comma-separated structured content", () => {
    expect(parseFields("chat_name=Bride squad, message=hi")).toEqual([
      { key: "chat_name", value: "Bride squad" },
      { key: "message", value: "hi" },
    ])
  })

  it("keeps a comma inside a value out of the field split", () => {
    expect(parseFields("chat_name=a, b, message=hi")).toEqual([
      { key: "chat_name", value: "a, b" },
      { key: "message", value: "hi" },
    ])
  })

  it("keeps a mid-string key= without a comma prefix inside the previous value", () => {
    expect(parseFields("a=1 b=2, c=3")).toEqual([
      { key: "a", value: "1 b=2" },
      { key: "c", value: "3" },
    ])
  })
})

describe("isStructured", () => {
  it("treats a leading key= token as structured, free text as not", () => {
    expect(isStructured("chat_name=Bride squad")).toBe(true)
    expect(isStructured("just a sentence")).toBe(false)
  })
})
