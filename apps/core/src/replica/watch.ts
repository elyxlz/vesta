export interface WatchManager {
  watch: (agent: string) => void
  unwatch: (agent: string) => void
  desired: () => string[]
}

export function createWatchManager(): WatchManager {
  const agents = new Set<string>()
  return {
    watch: (agent) => {
      agents.add(agent)
    },
    unwatch: (agent) => {
      agents.delete(agent)
    },
    desired: () => [...agents],
  }
}
