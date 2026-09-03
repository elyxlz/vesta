import type { Delta } from "./deltas";
import type { NotificationEvent } from "./events";
import type { HelloFrame, SnapshotFrame } from "./frames";
import type {
  AgentInfo,
  DeviceInfo,
  DeviceKind,
  DevicePlace,
  DevicePosition,
  GatewayInfo,
  Tree,
} from "./tree";

export type ParsedFrame =
  | { kind: "hello"; frame: HelloFrame }
  | { kind: "snapshot"; frame: SnapshotFrame }
  | { kind: "delta"; delta: Delta }
  | { kind: "unknown" };

const UNKNOWN: ParsedFrame = { kind: "unknown" };

// Core trusts vestad's serialization (additive-only within the served version window,
// contract-tested at the fixture seam), so the parser routes on `type` and the
// fields it keys on, then asserts the trusted sub-shapes. Anything it cannot
// classify becomes `unknown`, which the reducer skips by rule.
export function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function arr(value: unknown): unknown[] | null {
  return Array.isArray(value) ? (value as unknown[]) : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

export function parseServerFrame(raw: string): ParsedFrame {
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch {
    return UNKNOWN;
  }
  const frame = record(json);
  if (frame === null) return UNKNOWN;
  const type = str(frame.type);
  if (type === null) return UNKNOWN;
  switch (type) {
    case "hello":
      return parseHello(frame);
    case "snapshot":
      return parseSnapshot(frame);
    case "state":
    case "agent":
    case "agent_removed":
    case "agent_notifications":
    case "user_notification":
    case "presence":
    case "devices":
      return parseDelta(type, frame);
    default:
      return UNKNOWN;
  }
}

function parseHello(frame: Record<string, unknown>): ParsedFrame {
  const version = str(frame.version);
  const minSupported = str(frame.min_supported);
  if (version === null || minSupported === null) return UNKNOWN;
  return { kind: "hello", frame: { type: "hello", version, minSupported } };
}

function parseSnapshot(frame: Record<string, unknown>): ParsedFrame {
  if (record(frame.tree) === null) return UNKNOWN;
  return {
    kind: "snapshot",
    frame: { type: "snapshot", tree: frame.tree as Tree },
  };
}

function parseDelta(type: string, frame: Record<string, unknown>): ParsedFrame {
  switch (type) {
    case "state": {
      if (str(frame.scope) !== "gateway" || record(frame.value) === null)
        return UNKNOWN;
      return {
        kind: "delta",
        delta: {
          type: "state",
          scope: "gateway",
          value: frame.value as GatewayInfo,
        },
      };
    }
    case "agent": {
      const name = str(frame.name);
      if (name === null || record(frame.info) === null) return UNKNOWN;
      return {
        kind: "delta",
        delta: { type: "agent", name, info: frame.info as AgentInfo },
      };
    }
    case "agent_removed": {
      const name = str(frame.name);
      if (name === null) return UNKNOWN;
      return { kind: "delta", delta: { type: "agent_removed", name } };
    }
    case "agent_notifications": {
      const agent = str(frame.agent);
      const pending = arr(frame.pending);
      if (agent === null || pending === null) return UNKNOWN;
      return {
        kind: "delta",
        delta: {
          type: "agent_notifications",
          agent,
          pending: pending as NotificationEvent[],
        },
      };
    }
    case "user_notification":
      return parseUserNotification(frame);
    case "presence": {
      const anyFocused = bool(frame.any_focused);
      if (anyFocused === null) return UNKNOWN;
      return { kind: "delta", delta: { type: "presence", anyFocused } };
    }
    case "devices": {
      const raw = arr(frame.devices);
      if (raw === null) return UNKNOWN;
      const devices = raw.map(parseDevice);
      if (devices.some((device) => device === null)) return UNKNOWN;
      return {
        kind: "delta",
        delta: { type: "devices", devices: devices.filter(isPresent) },
      };
    }
    default:
      return UNKNOWN;
  }
}

function isPresent<T>(value: T | null): value is T {
  return value !== null;
}

function parseUserNotification(frame: Record<string, unknown>): ParsedFrame {
  const id = num(frame.id);
  const at = num(frame.at);
  const agent = str(frame.agent);
  const kind = str(frame.kind);
  const title = str(frame.title);
  const body = str(frame.body);
  if (id === null || at === null || agent === null) return UNKNOWN;
  if (kind === null || title === null || body === null) return UNKNOWN;
  return {
    kind: "delta",
    delta: { type: "user_notification", id, at, agent, kind, title, body },
  };
}

const DEVICE_KINDS: readonly DeviceKind[] = [
  "web",
  "mobile",
  "desktop",
  "unknown",
];

function parseDevice(value: unknown): DeviceInfo | null {
  const device = record(value);
  if (device === null) return null;
  const id = str(device.id);
  const kind = str(device.kind);
  const present = bool(device.present);
  const lastSeen = str(device.lastSeen);
  const pushEnabled = bool(device.pushEnabled);
  if (
    id === null ||
    kind === null ||
    present === null ||
    lastSeen === null ||
    pushEnabled === null
  ) {
    return null;
  }
  if (!DEVICE_KINDS.includes(kind as DeviceKind)) return null;
  const descriptor = device.descriptor === null ? null : str(device.descriptor);
  if (descriptor === null && device.descriptor !== null) return null;
  const context = parseDeviceContext(device);
  if (context === null) return null;
  return {
    id,
    kind: kind as DeviceKind,
    descriptor,
    present,
    lastSeen,
    pushEnabled,
    ...context,
  };
}

// The user-context facet of a device: each field is absent or null for "not reported", and any
// other malformed value fails the whole device.
function parseDeviceContext(
  device: Record<string, unknown>,
): Pick<DeviceInfo, "timezone" | "position" | "positionAt"> | null {
  const timezone = nullableStr(device.timezone);
  const positionAt = nullableStr(device.positionAt);
  if (timezone === undefined || positionAt === undefined) return null;
  const position =
    device.position == null ? null : parsePosition(device.position);
  if (position === null && device.position != null) return null;
  return { timezone, position, positionAt };
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// An optional string field: absent or null is null; anything but a string is `undefined` (malformed).
function nullableStr(value: unknown): string | null | undefined {
  if (value == null) return null;
  return str(value) ?? undefined;
}

function parsePosition(value: unknown): DevicePosition | null {
  const position = record(value);
  if (position === null) return null;
  const latitude = num(position.latitude);
  const longitude = num(position.longitude);
  if (latitude === null || longitude === null) return null;
  const accuracyM = position.accuracyM == null ? null : num(position.accuracyM);
  if (accuracyM === null && position.accuracyM != null) return null;
  let place: DevicePlace | null = null;
  if (position.place != null) {
    const raw = record(position.place);
    if (raw === null) return null;
    const city = nullableStr(raw.city);
    const region = nullableStr(raw.region);
    const country = nullableStr(raw.country);
    if (city === undefined || region === undefined || country === undefined)
      return null;
    place = { city, region, country };
  }
  return { latitude, longitude, accuracyM, place };
}
