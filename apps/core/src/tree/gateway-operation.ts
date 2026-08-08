import type { GatewayUpdateOperation, GatewayUpdatePhase, Tree } from "../protocol/tree"

const PHASES: readonly GatewayUpdatePhase[] = ["snapshotting", "applying", "restarting", "failed"]

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null
}

// The one reader of the gateway's operation branch, for every app. The phase is the one field worth
// narrowing: an app that met a phase from a newer gateway and rendered it as "something is happening"
// would lock the user on a screen it cannot describe or resolve, so an unknown phase reads as idle.
export function selectGatewayOperation(tree: Tree | null): GatewayUpdateOperation | null {
  const operation = record(tree?.gateway.operation)
  if (operation === null) return null
  const phase = str(operation.phase)
  if (phase === null || !PHASES.includes(phase as GatewayUpdatePhase)) return null
  const targetVersion = str(operation.targetVersion)
  if (targetVersion === null) return null
  const warnings = Array.isArray(operation.warnings)
    ? operation.warnings.filter((warning): warning is string => typeof warning === "string")
    : []
  return {
    kind: "update",
    phase: phase as GatewayUpdatePhase,
    agent: str(operation.agent),
    done: num(operation.done),
    total: num(operation.total),
    targetVersion,
    warnings,
    error: str(operation.error),
  }
}

// The one line every surface shows for a running update. Progress counts from the agent being worked
// on, so the first of four reads "1/4" rather than "0/4".
export function gatewayOperationLabel(operation: GatewayUpdateOperation): string {
  switch (operation.phase) {
    case "snapshotting": {
      const { agent, done, total } = operation
      if (agent === null) return "backing up your agents"
      if (done === null || total === null) return `backing up ${agent}`
      return `backing up ${agent} ${String(done + 1)}/${String(total)}`
    }
    case "applying":
      return "installing"
    case "restarting":
      return "restarting"
    case "failed":
      return "update failed"
  }
}
