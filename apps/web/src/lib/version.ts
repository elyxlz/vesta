/**
 * Compare two dotted version strings numerically (semver-ish).
 * Returns -1 if a < b, 1 if a > b, 0 if equal.
 * Non-numeric segments (e.g. prerelease suffixes like "0-rc1") parse via their
 * leading integer; a missing segment counts as 0.
 */
export function compareVersions(a: string, b: string): number {
  const parse = (segment: string) => {
    const value = Number.parseInt(segment, 10);
    return Number.isNaN(value) ? 0 : value;
  };
  const left = a.split(".");
  const right = b.split(".");
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    const lhs = parse(left[i] ?? "0");
    const rhs = parse(right[i] ?? "0");
    if (lhs > rhs) return 1;
    if (lhs < rhs) return -1;
  }
  return 0;
}
