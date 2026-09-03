import type { AgentInfo, ServiceInfo, Tree } from "../protocol/tree";

// The roster row both clients hold: core's per-agent node info plus the `name` the tree keys agents
// by (core's AgentInfo carries no name of its own).
export type AgentRow = AgentInfo & { name: string };

export function rosterFromTree(tree: Tree | null): AgentRow[] {
  return tree
    ? Object.entries(tree.agents).map(([name, node]) => ({
        name,
        ...node.info,
      }))
    : [];
}

function servicesEqual(
  a: Record<string, ServiceInfo>,
  b: Record<string, ServiceInfo>,
): boolean {
  const keys = Object.keys(a);
  if (keys.length !== Object.keys(b).length) return false;
  return keys.every(
    (key) =>
      a[key]?.port === b[key]?.port &&
      a[key]?.rev === b[key]?.rev &&
      a[key]?.public === b[key]?.public,
  );
}

// Structural compare so an unrelated tree delta (a notification landing on one agent) does not hand
// every roster consumer a fresh array through useReplica.
export function rostersEqual(a: AgentRow[], b: AgentRow[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((row, index) => {
    const other = b[index];
    return other !== undefined && rowsEqual(row, other);
  });
}

const ROW_SCALAR_KEYS = [
  "name",
  "status",
  "activityState",
  "buildPhase",
  "operation",
  "startedAt",
] as const;

function rowsEqual(row: AgentRow, other: AgentRow): boolean {
  return (
    ROW_SCALAR_KEYS.every((key) => other[key] === row[key]) &&
    (other.booting ?? false) === (row.booting ?? false) &&
    rateLimitsEqual(row.rateLimited, other.rateLimited) &&
    servicesEqual(row.services, other.services)
  );
}

function rateLimitsEqual(
  a: AgentRow["rateLimited"],
  b: AgentRow["rateLimited"],
): boolean {
  if (a == null || b == null) return a == null && b == null;
  return a.window === b.window && a.resetsAt === b.resetsAt;
}
