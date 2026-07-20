// Release-version comparison for the drift policy (distinct from the protocol floor in
// version.ts). Fail-open by design: an unparseable version on either side yields null, so a
// dev build carrying a non-semver string is never judged ahead of or behind the gateway.

function parseParts(version: string): number[] | null {
  const core = version.split("-")[0] ?? ""
  const parts = core.split(".")
  const nums: number[] = []
  for (const part of parts) {
    if (!/^\d+$/.test(part)) return null
    nums.push(Number(part))
  }
  return nums.length > 0 ? nums : null
}

// 1 when `a` is newer, -1 when older, 0 when equal, null when either side is unparseable.
export function compareReleaseVersions(a: string, b: string): number | null {
  const left = parseParts(a)
  const right = parseParts(b)
  if (left === null || right === null) return null
  const len = Math.max(left.length, right.length)
  for (let index = 0; index < len; index++) {
    const diff = (left[index] ?? 0) - (right[index] ?? 0)
    if (diff !== 0) return diff > 0 ? 1 : -1
  }
  return 0
}

// True only when the client is strictly newer than the gateway (the blocked direction).
// Fails open: an unparseable version on either side is never treated as ahead.
export function clientAheadOfGateway(clientVersion: string, gatewayVersion: string): boolean {
  const cmp = compareReleaseVersions(clientVersion, gatewayVersion)
  return cmp !== null && cmp > 0
}
