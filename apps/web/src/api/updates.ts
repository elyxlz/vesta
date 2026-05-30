import { compareVersions } from "@/lib/version";

export function isNewer(latest: string, current: string): boolean {
  return compareVersions(latest, current) > 0;
}
