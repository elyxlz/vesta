// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest"
import { act, cleanup, render, screen } from "@testing-library/react"

import { useReplica } from "./use-replica"
import { createReplica } from "../replica/store"
import type { ReactElement } from "react"
import type { Replica } from "../replica/store"
import type { AgentInfo, GatewayInfo, Tree } from "../protocol/tree"

function baseGateway(): GatewayInfo {
  return {
    version: "0.2.0",
    channel: "stable",
    autoUpdate: true,
    port: 4111,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: false,
    latestVersion: null,
    managed: false,
  }
}

function baseTree(): Tree {
  return { gateway: baseGateway(), agents: {} }
}

function agentInfo(): AgentInfo {
  return { status: "alive", activityState: "idle", buildPhase: null, startedAt: null, services: {} }
}

function Version({ replica, onRender }: { replica: Replica; onRender: () => void }): ReactElement {
  const version = useReplica(replica, (tree) => tree?.gateway.version ?? "")
  onRender()
  return <span data-testid="version">{version}</span>
}

function AgentNames({
  replica,
  onRender,
}: {
  replica: Replica
  onRender: () => void
}): ReactElement {
  const names = useReplica(
    replica,
    (tree) => Object.keys(tree?.agents ?? {}),
    (a, b) => a.length === b.length && a.every((name, index) => name === b[index]),
  )
  onRender()
  return <span data-testid="names">{names.join(",")}</span>
}

afterEach(cleanup)

describe("useReplica", () => {
  it("renders the selected slice and updates on a relevant delta", () => {
    const replica = createReplica()
    render(<Version replica={replica} onRender={() => undefined} />)
    expect(screen.getByTestId("version").textContent).toBe("")

    act(() => {
      replica.applySnapshot(baseTree())
    })
    expect(screen.getByTestId("version").textContent).toBe("0.2.0")

    act(() => {
      replica.applyDelta({
        type: "state",
        scope: "gateway",
        value: { ...baseGateway(), version: "0.3.0" },
      })
    })
    expect(screen.getByTestId("version").textContent).toBe("0.3.0")
  })

  it("does not re-render when an unrelated delta leaves the slice unchanged", () => {
    const replica = createReplica()
    let renders = 0
    render(<Version replica={replica} onRender={() => (renders += 1)} />)

    act(() => {
      replica.applySnapshot({
        ...baseTree(),
        agents: { scout: { info: agentInfo(), notifications: { pending: [] } } },
      })
    })
    const afterSnapshot = renders

    // A different agent's notifications change the tree but not the gateway.version slice.
    act(() => {
      replica.applyDelta({
        type: "notifications",
        agent: "scout",
        pending: [{ id: 1, type: "notification", source: "chat", summary: "hi" }],
      })
    })
    expect(renders).toBe(afterSnapshot)
    expect(screen.getByTestId("version").textContent).toBe("0.2.0")
  })

  it("keeps an array selector stable via the structural comparator (no infinite re-render)", () => {
    const replica = createReplica()
    let renders = 0
    render(<AgentNames replica={replica} onRender={() => (renders += 1)} />)

    act(() => {
      replica.applySnapshot({
        ...baseTree(),
        agents: {
          alpha: { info: agentInfo(), notifications: { pending: [] } },
          bravo: { info: agentInfo(), notifications: { pending: [] } },
        },
      })
    })
    expect(screen.getByTestId("names").textContent).toBe("alpha,bravo")
    const afterSnapshot = renders

    // Gateway-only delta: the agent-name array is structurally identical, so the memo
    // returns the same reference and the component does not re-render.
    act(() => {
      replica.applyDelta({
        type: "state",
        scope: "gateway",
        value: { ...baseGateway(), version: "9.9.9" },
      })
    })
    expect(renders).toBe(afterSnapshot)
    expect(screen.getByTestId("names").textContent).toBe("alpha,bravo")
  })
})
