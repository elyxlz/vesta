import { describe, expect, it, vi } from "vitest"
import type { HttpClient } from "../transport/http"
import {
  VERSION_CHECK_TIMEOUT_MS,
  checkForGatewayUpdate,
  triggerGatewayRestart,
  triggerGatewayUpdate,
} from "./gateway-update"

function httpWith(request: HttpClient["request"]): HttpClient {
  return { request, json: vi.fn() }
}

describe("triggerGatewayUpdate", () => {
  it("POSTs /gateway/update and returns true on accept", async () => {
    const request = vi.fn().mockResolvedValue(new Response())
    const ok = await triggerGatewayUpdate(httpWith(request))

    expect(ok).toBe(true)
    const call = request.mock.calls[0]
    if (!call) throw new Error("no request")
    expect(call[0]).toBe("/gateway/update")
    expect((call[1] as RequestInit).method).toBe("POST")
  })

  it("returns false when vestad rejects the request", async () => {
    const request = vi.fn().mockRejectedValue(new Error("down"))
    expect(await triggerGatewayUpdate(httpWith(request))).toBe(false)
  })
})

describe("triggerGatewayRestart", () => {
  it("POSTs /gateway/restart and returns true on accept", async () => {
    const request = vi.fn().mockResolvedValue(new Response())
    const ok = await triggerGatewayRestart(httpWith(request))

    expect(ok).toBe(true)
    const call = request.mock.calls[0]
    if (!call) throw new Error("no request")
    expect(call[0]).toBe("/gateway/restart")
    expect((call[1] as RequestInit).method).toBe("POST")
  })

  it("returns false when vestad rejects the request", async () => {
    const request = vi.fn().mockRejectedValue(new Error("down"))
    expect(await triggerGatewayRestart(httpWith(request))).toBe(false)
  })
})

describe("checkForGatewayUpdate", () => {
  it("POSTs /version/check under the version-check timeout and ignores the body", async () => {
    const timeout = vi.spyOn(AbortSignal, "timeout")
    const request = vi.fn().mockResolvedValue(new Response())
    await checkForGatewayUpdate(httpWith(request))

    const call = request.mock.calls[0]
    if (!call) throw new Error("no request")
    expect(call[0]).toBe("/version/check")
    const init = call[1] as RequestInit
    expect(init.method).toBe("POST")
    expect(init.signal).toBeInstanceOf(AbortSignal)
    expect(timeout).toHaveBeenCalledWith(VERSION_CHECK_TIMEOUT_MS)
    timeout.mockRestore()
  })

  it("propagates a transport failure so callers can reflect it", async () => {
    const request = vi.fn().mockRejectedValue(new Error("down"))
    await expect(checkForGatewayUpdate(httpWith(request))).rejects.toThrow("down")
  })
})
