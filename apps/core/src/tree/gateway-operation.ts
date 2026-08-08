import type {
  GatewayOperation,
  GatewayOperationKind,
  GatewayOperationPhase,
  Tree,
} from "../protocol/tree"

const PHASES: readonly GatewayOperationPhase[] = [
  "snapshotting",
  "applying",
  "restarting",
  "failed",
]
const KINDS: readonly GatewayOperationKind[] = ["update", "restart"]

// The one reader of the gateway's operation branch, for every app. The shape is trusted like every
// sibling tree field (vestad's serialization is contract-tested at the fixture seam); the kind and
// the phase are the two fields narrowed, because an app that met either from a newer gateway and
// rendered it as "something is happening" would lock the user on a screen it cannot describe or
// resolve, so an unknown kind or phase reads as idle.
export function selectGatewayOperation(tree: Tree | null): GatewayOperation | null {
  const operation = tree?.gateway.operation ?? null
  if (operation === null) return null
  if (!KINDS.includes(operation.kind) || !PHASES.includes(operation.phase)) return null
  return operation
}

// Structural equality for the replica subscription: every delta rebuilds the tree, so the selected
// operation must compare by value or each delta would read as a change and re-render.
export function gatewayOperationsEqual(
  a: GatewayOperation | null,
  b: GatewayOperation | null,
): boolean {
  if (a === null || b === null) return a === b
  return (
    a.kind === b.kind &&
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

// The one line every surface shows for a running operation. Progress counts from the agent being
// worked on, so the first of four reads "1/4" rather than "0/4". A restart is only ever
// "restarting", the phase an update ends on.
export function gatewayOperationLabel(operation: GatewayOperation): string {
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
