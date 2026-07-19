export interface WatchManager {
  // Adds a reference for an agent; returns true only on the 0->1 transition, i.e. when a wire
  // WATCH is newly due. Independent subscribers (the chat view-model watching the active agent,
  // the notification funnel watching the whole alive fleet) can each watch the same agent.
  watch: (agent: string) => boolean
  // Removes a reference; returns true only on the 1->0 transition, i.e. when a wire UNWATCH is
  // due. Unwatching an unreferenced agent is a no-op that returns false.
  unwatch: (agent: string) => boolean
  // Drops an agent regardless of its reference count (the server already cancelled the watch,
  // e.g. on agent_removed), so it isn't replayed on reconnect.
  drop: (agent: string) => void
  desired: () => string[]
}

export function createWatchManager(): WatchManager {
  const refs = new Map<string, number>()
  return {
    watch: (agent) => {
      const next = (refs.get(agent) ?? 0) + 1
      refs.set(agent, next)
      return next === 1
    },
    unwatch: (agent) => {
      const current = refs.get(agent)
      if (current === undefined) return false
      if (current <= 1) {
        refs.delete(agent)
        return true
      }
      refs.set(agent, current - 1)
      return false
    },
    drop: (agent) => {
      refs.delete(agent)
    },
    desired: () => [...refs.keys()],
  }
}
