import type { AgentInfo, Tree } from "@vesta/core";

export type AgentRow = AgentInfo & { name: string };

export function rosterFromTree(tree: Tree | null): AgentRow[] {
  return tree
    ? Object.entries(tree.agents).map(([name, node]) => ({
        name,
        ...node.info,
      }))
    : [];
}

// Structural compare so an unrelated tree delta (a notification landing on one agent)
// does not hand every roster consumer a fresh array through useReplica.
export function rostersEqual(a: AgentRow[], b: AgentRow[]): boolean {
  return (
    a.length === b.length &&
    a.every((row, index) => {
      const other = b[index];
      return (
        !!other &&
        other.name === row.name &&
        other.status === row.status &&
        other.activityState === row.activityState &&
        other.startedAt === row.startedAt
      );
    })
  );
}
