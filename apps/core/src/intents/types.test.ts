import { describe, expect, it } from "vitest"

import { createSendMessageIntent } from "./types"

describe("createSendMessageIntent", () => {
  it("stamps a generated id and carries the message body", () => {
    const intent = createSendMessageIntent(
      "scout",
      { text: "ship it", input_method: "typed" },
      () => "intent-1",
    )
    expect(intent).toEqual({
      kind: "send_message",
      id: "intent-1",
      agent: "scout",
      body: { text: "ship it", input_method: "typed" },
    })
  })

  it("uses the injected generator for each intent id", () => {
    let counter = 0
    const newId = (): string => `intent-${String((counter += 1))}`
    const first = createSendMessageIntent("scout", { text: "a" }, newId)
    const second = createSendMessageIntent("scout", { text: "b" }, newId)
    expect([first.id, second.id]).toEqual(["intent-1", "intent-2"])
  })
})
