import { describe, expect, it } from "vitest"
import {
  enqueuePillNotification,
  pillDisplayLine,
  pillVisibleWhileViewing,
  type PillNotification,
} from "./notifications-pill"

function item(id: number, kind: string, agent = "aria"): PillNotification {
  return { id, kind, agent, title: `${kind} ${String(id)}`, body: "", orbState: null }
}

describe("enqueuePillNotification", () => {
  it("clusters a new item after the last queued item of its kind", () => {
    const queue = [item(0, "message"), item(1, "needs_user"), item(2, "task")]
    const next = enqueuePillNotification(queue, item(3, "needs_user"))
    expect(next.map((entry) => entry.id)).toEqual([0, 1, 3, 2])
  })

  it("appends a kind with no group yet", () => {
    const queue = [item(0, "message")]
    const next = enqueuePillNotification(queue, item(1, "agent_status"))
    expect(next.map((entry) => entry.id)).toEqual([0, 1])
  })

  it("keeps arrival order within a kind", () => {
    let queue: PillNotification[] = []
    queue = enqueuePillNotification(queue, item(0, "task"))
    queue = enqueuePillNotification(queue, item(1, "message"))
    queue = enqueuePillNotification(queue, item(2, "task"))
    queue = enqueuePillNotification(queue, item(3, "task"))
    expect(queue.map((entry) => entry.id)).toEqual([0, 2, 3, 1])
  })
})

describe("pillVisibleWhileViewing", () => {
  it("hides a message from the agent whose page is open", () => {
    expect(pillVisibleWhileViewing(item(0, "message", "aria"), "aria")).toBe(false)
  })

  it("shows a message from any other agent", () => {
    expect(pillVisibleWhileViewing(item(0, "message", "aria"), "apollo")).toBe(true)
  })

  it("shows every non-message kind even for the viewed agent", () => {
    for (const kind of ["needs_user", "task", "agent_status"]) {
      expect(pillVisibleWhileViewing(item(0, kind, "aria"), "aria")).toBe(true)
    }
  })
})

describe("pillDisplayLine", () => {
  it("joins a title and body as title: body", () => {
    expect(pillDisplayLine({ title: "aria", body: "hi there" })).toBe("aria: hi there")
  })

  it("renders a bodiless notification as the title alone", () => {
    expect(pillDisplayLine({ title: "aria stopped", body: "" })).toBe("aria stopped")
  })
})
