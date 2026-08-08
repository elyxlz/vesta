import { describe, expect, it } from "vitest"

import type { GatewayInfo, GatewayUpdateOperation, Tree } from "../protocol/tree"
import {
  gatewayOperationLabel,
  gatewayOperationsEqual,
  selectGatewayOperation,
} from "./gateway-operation"

function treeWith(operation: unknown): Tree {
  const gateway = {
    version: "0.1.189",
    channel: "stable",
    autoUpdate: true,
    port: 4111,
    lan: { exposed: false, url: null },
    tunnelUrl: null,
    updateAvailable: true,
    latestVersion: "0.1.190",
    managed: false,
    operation,
  } as unknown as GatewayInfo
  return { gateway, agents: {}, devices: [] }
}

describe("selectGatewayOperation", () => {
  it("reads a running update off the gateway branch", () => {
    const operation = selectGatewayOperation(
      treeWith({
        kind: "update",
        phase: "snapshotting",
        agent: "axel",
        done: 1,
        total: 4,
        targetVersion: "0.1.190",
        warnings: ["mona: backup failed (disk full)"],
        error: null,
      }),
    )
    expect(operation).toEqual({
      kind: "update",
      phase: "snapshotting",
      agent: "axel",
      done: 1,
      total: 4,
      targetVersion: "0.1.190",
      warnings: ["mona: backup failed (disk full)"],
      error: null,
    })
  })

  it("reads an idle gateway, a missing field, and a missing tree as no operation", () => {
    expect(selectGatewayOperation(treeWith(null))).toBeNull()
    expect(selectGatewayOperation(treeWith(undefined))).toBeNull()
    expect(selectGatewayOperation(null)).toBeNull()
  })

  it("ignores a phase it does not know, so a newer gateway never locks this app on an unknown state", () => {
    expect(
      selectGatewayOperation(
        treeWith({
          kind: "update",
          phase: "vacuuming",
          agent: null,
          done: null,
          total: null,
          targetVersion: "0.1.190",
          warnings: [],
          error: null,
        }),
      ),
    ).toBeNull()
  })
})

describe("gatewayOperationsEqual", () => {
  const operation = (overrides: Partial<GatewayUpdateOperation> = {}): GatewayUpdateOperation => ({
    kind: "update",
    phase: "snapshotting",
    agent: "axel",
    done: 1,
    total: 4,
    targetVersion: "0.1.190",
    warnings: ["mona: backup failed (disk full)"],
    error: null,
    ...overrides,
  })

  it("treats structurally identical operations as equal, so a rebuilt tree does not re-render", () => {
    expect(gatewayOperationsEqual(operation(), operation())).toBe(true)
    expect(gatewayOperationsEqual(null, null)).toBe(true)
  })

  it("sees every field that moves during an update", () => {
    expect(gatewayOperationsEqual(operation(), null)).toBe(false)
    expect(gatewayOperationsEqual(operation(), operation({ done: 2 }))).toBe(false)
    expect(gatewayOperationsEqual(operation(), operation({ phase: "applying" }))).toBe(false)
    expect(gatewayOperationsEqual(operation(), operation({ warnings: [] }))).toBe(false)
    expect(
      gatewayOperationsEqual(operation(), operation({ error: "while installing: curl failed" })),
    ).toBe(false)
  })
})

describe("gatewayOperationLabel", () => {
  it("names the agent and its place in the queue while backing up", () => {
    expect(
      gatewayOperationLabel({
        kind: "update",
        phase: "snapshotting",
        agent: "axel",
        done: 1,
        total: 4,
        targetVersion: "0.1.190",
        warnings: [],
        error: null,
      }),
    ).toBe("backing up axel 2/4")
  })

  it("falls back to a plain phrase when there is no agent to name", () => {
    const base = {
      kind: "update" as const,
      agent: null,
      done: null,
      total: null,
      targetVersion: "0.1.190",
      warnings: [],
      error: null,
    }
    expect(gatewayOperationLabel({ ...base, phase: "snapshotting" })).toBe("backing up your agents")
    expect(gatewayOperationLabel({ ...base, phase: "applying" })).toBe("installing")
    expect(gatewayOperationLabel({ ...base, phase: "restarting" })).toBe("restarting")
    expect(gatewayOperationLabel({ ...base, phase: "failed" })).toBe("update failed")
  })
})
