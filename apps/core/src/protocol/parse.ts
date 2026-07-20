import type { Delta } from "./deltas"
import type { NotificationEvent } from "./events"
import type { HelloFrame, SnapshotFrame } from "./frames"
import type { AgentInfo, GatewayInfo, Tree } from "./tree"

export type ParsedFrame =
  | { kind: "hello"; frame: HelloFrame }
  | { kind: "snapshot"; frame: SnapshotFrame }
  | { kind: "delta"; delta: Delta }
  | { kind: "unknown" }

const UNKNOWN: ParsedFrame = { kind: "unknown" }

// Core trusts vestad's serialization within a protocol version (additive-only,
// contract-tested at the fixture seam), so the parser routes on `type` and the
// fields it keys on, then asserts the trusted sub-shapes. Anything it cannot
// classify becomes `unknown`, which the reducer skips by rule.
function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null
}

function num(value: unknown): number | null {
  return typeof value === "number" ? value : null
}

function arr(value: unknown): unknown[] | null {
  return Array.isArray(value) ? (value as unknown[]) : null
}

export function parseServerFrame(raw: string): ParsedFrame {
  let json: unknown
  try {
    json = JSON.parse(raw)
  } catch {
    return UNKNOWN
  }
  const frame = record(json)
  if (frame === null) return UNKNOWN
  const type = str(frame.type)
  if (type === null) return UNKNOWN
  switch (type) {
    case "hello":
      return parseHello(frame)
    case "snapshot":
      return parseSnapshot(frame)
    case "state":
    case "agent":
    case "agent_removed":
    case "notifications":
    case "alert":
      return parseDelta(type, frame)
    default:
      return UNKNOWN
  }
}

function parseHello(frame: Record<string, unknown>): ParsedFrame {
  const version = str(frame.version)
  const protocol = num(frame.protocol)
  const floor = num(frame.floor)
  if (version === null || protocol === null || floor === null) return UNKNOWN
  return { kind: "hello", frame: { type: "hello", version, protocol, floor } }
}

function parseSnapshot(frame: Record<string, unknown>): ParsedFrame {
  if (record(frame.tree) === null) return UNKNOWN
  return { kind: "snapshot", frame: { type: "snapshot", tree: frame.tree as Tree } }
}

function parseDelta(type: string, frame: Record<string, unknown>): ParsedFrame {
  switch (type) {
    case "state": {
      if (str(frame.scope) !== "gateway" || record(frame.value) === null) return UNKNOWN
      return {
        kind: "delta",
        delta: { type: "state", scope: "gateway", value: frame.value as GatewayInfo },
      }
    }
    case "agent": {
      const name = str(frame.name)
      if (name === null || record(frame.info) === null) return UNKNOWN
      return { kind: "delta", delta: { type: "agent", name, info: frame.info as AgentInfo } }
    }
    case "agent_removed": {
      const name = str(frame.name)
      if (name === null) return UNKNOWN
      return { kind: "delta", delta: { type: "agent_removed", name } }
    }
    case "notifications": {
      const agent = str(frame.agent)
      const pending = arr(frame.pending)
      if (agent === null || pending === null) return UNKNOWN
      return {
        kind: "delta",
        delta: { type: "notifications", agent, pending: pending as NotificationEvent[] },
      }
    }
    case "alert": {
      const agent = str(frame.agent)
      const kind = str(frame.kind)
      const title = str(frame.title)
      const body = str(frame.body)
      if (agent === null || kind === null || title === null || body === null) return UNKNOWN
      return { kind: "delta", delta: { type: "alert", agent, kind, title, body } }
    }
    default:
      return UNKNOWN
  }
}
