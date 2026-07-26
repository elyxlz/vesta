import { describe, expect, it } from "vitest"

import type { AgentStatus } from "../protocol/tree"
import { agentOrbState, agentStatusLabel, orbIsLive, type OrbVisualState } from "./agent-status"

const EVERY_STATUS: AgentStatus[] = [
  "alive",
  "starting",
  "setting_up",
  "not_authenticated",
  "unprovisioned",
  "restarting",
  "rebuilding",
  "stopped",
  "dead",
  "not_found",
]

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

describe("agentStatusLabel", () => {
  it("names the user as the actor for the states only they can resolve", () => {
    expect(agentStatusLabel("not_authenticated", "idle")).toBe("needs you to sign in")
    expect(agentStatusLabel("unprovisioned", "idle")).toBe("needs to be set up")
  })

  it("keeps the waiting labels distinct from a plainly stopped agent", () => {
    expect(agentStatusLabel("stopped", "idle")).toBe("stopped")
  })

  it("says what an agent is doing while it works", () => {
    expect(agentStatusLabel("starting", "idle")).toBe("waking up...")
    expect(agentStatusLabel("setting_up", "idle")).toBe("setting up...")
    expect(agentStatusLabel("restarting", "idle")).toBe("restarting...")
    expect(agentStatusLabel("rebuilding", "idle")).toBe("updating...")
  })

  it("distinguishes a thinking agent from an idle one", () => {
    expect(agentStatusLabel("alive", "thinking")).toBe("thinking")
    expect(agentStatusLabel("alive", "idle")).toBe("alive")
  })

  it("ignores the activity state unless the agent is alive", () => {
    expect(agentStatusLabel("rebuilding", "thinking")).toBe("updating...")
    expect(agentStatusLabel("stopped", "thinking")).toBe("stopped")
  })

  it.each(EVERY_STATUS)("never leaks the raw %s enum into the UI", (status) => {
    const label = agentStatusLabel(status, "idle")
    expect(label).not.toBe("")
    expect(label).not.toContain("_")
  })
})
