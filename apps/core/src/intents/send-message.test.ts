import { describe, expect, it, vi } from "vitest"
import { ApiError, type HttpClient } from "../transport/http"
import { sendMessage } from "./send-message"

function httpWith(json: HttpClient["json"]): HttpClient {
  return { request: vi.fn(), json }
}

describe("sendMessage", () => {
  it("posts the intent under a fresh id and resolves null on accept", async () => {
    const json = vi.fn().mockResolvedValue({})
    const { id, outcome } = sendMessage(
      httpWith(json),
      "scout",
      { text: "hi", input_method: "typed" },
      () => "i-1",
    )

    expect(id).toBe("i-1")
    const call = json.mock.calls[0]
    if (!call) throw new Error("no POST")
    expect(call[0]).toBe("/agents/scout/app-chat/message")
    const body = JSON.parse((call[1] as { body: string }).body) as unknown
    expect(body).toEqual({ text: "hi", input_method: "typed", intent_id: "i-1" })
    expect(await outcome).toBeNull()
  })

  it.each([502, 503, 504])("maps a daemon-down %i to a retryable outcome", async (status) => {
    const json = vi.fn().mockRejectedValue(new ApiError(status, "unavailable"))
    const { outcome } = sendMessage(httpWith(json), "scout", { text: "hi" }, () => "i-2")
    expect(await outcome).toBe("retry")
  })

  it("maps a network/timeout failure (no HTTP status) to a retryable outcome", async () => {
    const json = vi.fn().mockRejectedValue(new Error("network down"))
    const { outcome } = sendMessage(httpWith(json), "scout", { text: "hi" }, () => "i-net")
    expect(await outcome).toBe("retry")
  })

  it("maps any other HTTP error to a failed outcome", async () => {
    const json = vi.fn().mockRejectedValue(new ApiError(500, "boom"))
    const { outcome } = sendMessage(httpWith(json), "scout", { text: "hi" }, () => "i-3")
    expect(await outcome).toBe("failed")
  })

  it("re-posts the same id when the generator returns an existing id (idempotent retry)", () => {
    const json = vi.fn().mockResolvedValue({})
    const { id } = sendMessage(httpWith(json), "scout", { text: "hi" }, () => "existing")
    expect(id).toBe("existing")
  })
})
