import type { AgentInfo, ServiceInfo, Tree } from "../protocol/tree"

// The roster row both clients hold: core's per-agent node info plus the `name` the tree keys agents
// by (core's AgentInfo carries no name of its own).
export type AgentRow = AgentInfo & { name: string }

export function rosterFromTree(tree: Tree | null): AgentRow[] {
  return tree ? Object.entries(tree.agents).map(([name, node]) => ({ name, ...node.info })) : []
}

function servicesEqual(a: Record<string, ServiceInfo>, b: Record<string, ServiceInfo>): boolean {
  const keys = Object.keys(a)
  if (keys.length !== Object.keys(b).length) return false
  return keys.every((key) => a[key]?.port === b[key]?.port && a[key]?.rev === b[key]?.rev)
}

// Structural compare so an unrelated tree delta (a notification landing on one agent) does not hand
// every roster consumer a fresh array through useReplica.
export function rostersEqual(a: AgentRow[], b: AgentRow[]): boolean {
  if (a.length !== b.length) return false
  return a.every((row, index) => {
    const other = b[index]
    if (other === undefined) return false
    return (
      other.name === row.name &&
      other.status === row.status &&
      other.activityState === row.activityState &&
      other.buildPhase === row.buildPhase &&
      other.startedAt === row.startedAt &&
      servicesEqual(row.services, other.services)
    )
  })
}
