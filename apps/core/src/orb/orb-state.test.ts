import { describe, expect, it } from "vitest"

import type { AgentStatus } from "../protocol/tree"
import { agentOrbState, orbIsLive, type OrbVisualState } from "./orb-state"

describe("agentOrbState", () => {
  it("distinguishes a thinking agent from an idle one", () => {
    expect(agentOrbState("alive", "thinking")).toBe("thinking")
    expect(agentOrbState("alive", "idle")).toBe("alive")
  })

  it.each<AgentStatus>(["starting", "setting_up", "restarting", "rebuilding"])(
    "keeps %s busy, because the agent resolves it on its own",
    (status) => {
      expect(agentOrbState(status, "idle")).toBe("busy")
    },
  )

  it.each<AgentStatus>(["not_authenticated", "unprovisioned"])(
    "turns the orb off for %s, which only the user can resolve",
    (status) => {
      expect(agentOrbState(status, "idle")).toBe("off")
    },
  )

  it.each<AgentStatus>(["stopped", "dead", "not_found"])("turns the orb off for %s", (status) => {
    expect(agentOrbState(status, "idle")).toBe("off")
  })

  it("ignores the activity state unless the agent is alive", () => {
    expect(agentOrbState("rebuilding", "thinking")).toBe("busy")
    expect(agentOrbState("stopped", "thinking")).toBe("off")
  })
})

describe("orbIsLive", () => {
  it.each<OrbVisualState>(["alive", "thinking", "busy"])("animates the %s orb", (state) => {
    expect(orbIsLive(state)).toBe(true)
  })

  it.each<OrbVisualState>(["off", "deleting"])("holds the %s orb still", (state) => {
    expect(orbIsLive(state)).toBe(false)
  })
})
