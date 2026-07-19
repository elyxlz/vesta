import { describe, expect, it } from "vitest"

import { encodeFrame, reauthFrame, unwatchFrame, watchFrame } from "./frames"
import type { HelloFrame, SnapshotFrame } from "./frames"
import type { NotificationEvent } from "./events"
import type { Tree } from "./tree"

describe("client frame constructors", () => {
  it("builds watch, unwatch, and reauth frames", () => {
    expect(watchFrame("scout")).toEqual({ type: "watch", agent: "scout" })
    expect(unwatchFrame("scout")).toEqual({ type: "unwatch", agent: "scout" })
    expect(reauthFrame("tok")).toEqual({ type: "reauth", token: "tok" })
  })

  it("encodes a client frame as JSON", () => {
    expect(encodeFrame(watchFrame("scout"))).toBe('{"type":"watch","agent":"scout"}')
  })
})

describe("server frame and tree shapes", () => {
  it("types a hello frame with version, protocol, and floor", () => {
    const hello: HelloFrame = { type: "hello", version: "0.2.0", protocol: 1, floor: 1 }
    expect(hello.protocol).toBe(1)
  })

  it("types a snapshot frame carrying the state tree", () => {
    const event: NotificationEvent = { id: 7, type: "notification", source: "sms", summary: "hi" }
    const tree: Tree = {
      gateway: {
        version: "0.2.0",
        channel: "stable",
        autoUpdate: true,
        port: 4111,
        lan: { exposed: false, url: null },
        tunnelUrl: null,
        updateAvailable: false,
        latestVersion: null,
        managed: false,
      },
      agents: {
        scout: {
          info: {
            status: "alive",
            activityState: "idle",
            buildPhase: null,
            startedAt: "2026-07-18T00:00:00Z",
            services: {},
          },
          notifications: { pending: [event] },
        },
      },
    }
    const snapshot: SnapshotFrame = { type: "snapshot", tree }
    expect(snapshot.tree.agents.scout?.notifications.pending[0]?.id).toBe(7)
  })
})
