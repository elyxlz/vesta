import type { GatewayUpdateOperation, GatewayUpdatePhase, Tree } from "../protocol/tree"

const PHASES: readonly GatewayUpdatePhase[] = ["snapshotting", "applying", "restarting", "failed"]

// The one reader of the gateway's operation branch, for every app. The shape is trusted like every
// sibling tree field (vestad's serialization is contract-tested at the fixture seam); the phase is
// the one field narrowed, because an app that met a phase from a newer gateway and rendered it as
// "something is happening" would lock the user on a screen it cannot describe or resolve, so an
// unknown phase reads as idle.
export function selectGatewayOperation(tree: Tree | null): GatewayUpdateOperation | null {
  const operation = tree?.gateway.operation ?? null
  if (operation === null || !PHASES.includes(operation.phase)) return null
  return operation
}

// Structural equality for the replica subscription: every delta rebuilds the tree, so the selected
// operation must compare by value or each delta would read as a change and re-render.
export function gatewayOperationsEqual(
  a: GatewayUpdateOperation | null,
  b: GatewayUpdateOperation | null,
): boolean {
  if (a === null || b === null) return a === b
  return (
    a.phase === b.phase &&
    a.agent === b.agent &&
    a.done === b.done &&
    a.total === b.total &&
    a.targetVersion === b.targetVersion &&
    a.error === b.error &&
    a.warnings.length === b.warnings.length &&
    a.warnings.every((warning, index) => b.warnings[index] === warning)
  )
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
