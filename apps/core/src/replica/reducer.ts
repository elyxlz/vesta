import type { Delta } from "../protocol/deltas"
import type { AgentNode, Tree } from "../protocol/tree"

export function reduceDelta(tree: Tree, delta: Delta): Tree {
  switch (delta.type) {
    case "state":
      return { ...tree, gateway: delta.value }
    case "agent": {
      const prev = tree.agents[delta.name]
      const node: AgentNode = {
        info: delta.info,
        notifications: prev?.notifications ?? { pending: [] },
      }
      return { ...tree, agents: { ...tree.agents, [delta.name]: node } }
    }
    case "agent_removed": {
      if (!(delta.name in tree.agents)) return tree
      const agents = Object.fromEntries(
        Object.entries(tree.agents).filter(([name]) => name !== delta.name),
      )
      return { ...tree, agents }
    }
    case "notifications": {
      const prev = tree.agents[delta.agent]
      if (prev === undefined) return tree
      const node: AgentNode = { ...prev, notifications: { pending: delta.pending } }
      return { ...tree, agents: { ...tree.agents, [delta.agent]: node } }
    }
    case "append":
    case "resync":
      return tree
  }
}
