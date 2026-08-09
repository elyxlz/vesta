// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render, screen } from "@testing-library/react"

import { UPDATED_NOTICE_MS, useUpdateResolution } from "./use-update-resolution"
import type { GatewayOperation } from "../protocol/tree"

function operation(kind: GatewayOperation["kind"]): GatewayOperation {
  return {
    kind,
    phase: "snapshotting",
    agent: null,
    done: null,
    total: null,
    targetVersion: kind === "update" ? "0.1.190" : null,
    warnings: [],
    error: null,
  }
}

function Harness({
  operation: running,
  version,
}: {
  operation: GatewayOperation | null
  version: string
}) {
  const updatedTo = useUpdateResolution(running, version)
  return <span data-testid="resolution">{updatedTo ?? "none"}</span>
}

function resolution(): string | null {
  return screen.getByTestId("resolution").textContent
}

describe("useUpdateResolution", () => {
  afterEach(() => {
    cleanup()
    vi.useRealTimers()
  })

  it("reports the version an update the client watched landed on", () => {
    const view = render(<Harness operation={operation("update")} version="0.1.189" />)
    expect(resolution()).toBe("none")
    view.rerender(<Harness operation={null} version="0.1.190" />)
    expect(resolution()).toBe("0.1.190")
  })

  it("clears the notice after its moment", async () => {
    vi.useFakeTimers()
    const view = render(<Harness operation={operation("update")} version="0.1.189" />)
    view.rerender(<Harness operation={null} version="0.1.190" />)
    expect(resolution()).toBe("0.1.190")
    await act(async () => {
      await vi.advanceTimersByTimeAsync(UPDATED_NOTICE_MS)
    })
    expect(resolution()).toBe("none")
  })

  it("resolves nothing for a restart, which lands on the same version", () => {
    const view = render(<Harness operation={operation("restart")} version="0.1.189" />)
    view.rerender(<Harness operation={null} version="0.1.189" />)
    expect(resolution()).toBe("none")
  })

  it("resolves nothing while there is no gateway branch yet", () => {
    const view = render(<Harness operation={operation("update")} version="" />)
    view.rerender(<Harness operation={null} version="" />)
    expect(resolution()).toBe("none")
  })

  it("resolves nothing for an operation the client never saw start", () => {
    const view = render(<Harness operation={null} version="0.1.189" />)
    view.rerender(<Harness operation={null} version="0.1.190" />)
    expect(resolution()).toBe("none")
  })

  it("lets a new operation supersede a still-showing notice", () => {
    const view = render(<Harness operation={operation("update")} version="0.1.189" />)
    view.rerender(<Harness operation={null} version="0.1.190" />)
    expect(resolution()).toBe("0.1.190")
    view.rerender(<Harness operation={operation("restart")} version="0.1.190" />)
    expect(resolution()).toBe("none")
  })
})
