import { describe, expect, it } from "vitest"

import type { AgentStatus } from "../protocol/tree"
import {
  agentIsConnectable,
  agentIsDown,
  agentNeedsUser,
  agentOrbState,
  agentStatusKind,
  agentStatusLabel,
  orbIsLive,
  type AgentStatusKind,
  type OrbVisualState,
} from "./agent-status"

const KIND_MEMBERS: Record<AgentStatusKind, AgentStatus[]> = {
  alive: ["alive"],
  working: ["starting", "setting_up", "restarting", "rebuilding"],
  "needs-user": ["not_authenticated", "unprovisioned"],
  down: ["stopped", "dead", "not_found"],
}

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

// Membership rather than case-by-case: asserting the whole set catches a status silently joining or
// leaving a group, which a per-status table does not.
describe("agentStatusKind", () => {
  it.each<AgentStatusKind>(["alive", "working", "needs-user", "down"])(
    "puts exactly the right statuses in %s",
    (kind) => {
      expect(EVERY_STATUS.filter((status) => agentStatusKind(status) === kind)).toEqual(
        KIND_MEMBERS[kind],
      )
    },
  )

  it("waits on the user only where the user is the one who can act", () => {
    expect(EVERY_STATUS.filter(agentNeedsUser)).toEqual(KIND_MEMBERS["needs-user"])
  })

  // An agent waiting on the user still answers, which is why chat history loads before sign-in.
  it("counts a waiting agent as connectable", () => {
    expect(EVERY_STATUS.filter(agentIsConnectable)).toEqual([
      "alive",
      "not_authenticated",
      "unprovisioned",
    ])
  })

  it("treats only the states with no container as down", () => {
    expect(EVERY_STATUS.filter(agentIsDown)).toEqual(KIND_MEMBERS.down)
  })

  it("never calls a status both connectable and down", () => {
    expect(EVERY_STATUS.filter((s) => agentIsConnectable(s) && agentIsDown(s))).toEqual([])
  })
})

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

describe("a running operation", () => {
  // A backup pauses the container, so the raw status reads `stopped` while restic works. Without
  // the operation winning, the orb would tell the user to restart an agent that is mid-backup.
  it("outranks a status the operation itself caused", () => {
    expect(agentOrbState("stopped", "idle", "backing_up")).toBe("busy")
    expect(agentStatusLabel("stopped", "idle", "backing_up")).toBe("backing up...")
  })

  it("keeps the orb alive while a restore tears the container down", () => {
    expect(agentOrbState("not_found", "idle", "restoring")).toBe("busy")
    expect(agentStatusLabel("not_found", "idle", "restoring")).toBe("restoring...")
  })

  it("leaves the status alone once the operation settles", () => {
    expect(agentOrbState("stopped", "idle", null)).toBe("off")
    expect(agentStatusLabel("stopped", "idle", null)).toBe("stopped")
  })

  it("defaults to no operation so a caller that has none reads the status", () => {
    expect(agentOrbState("alive", "idle")).toBe("alive")
    expect(agentStatusLabel("alive", "idle")).toBe("alive")
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
