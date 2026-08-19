export interface FingerprintResult {
  fingerprint: string;
  sources: string[];
  hashes: Record<string, string>;
  extras: string;
}
export interface StaleReasons {
  changed: string[];
  added: string[];
  removed: string[];
  extras: boolean;
  // The record predates per-file hashes, so nothing can be named.
  unknown: boolean;
}
export function staleReasons(
  record: { hashes?: Record<string, string>; extras?: string },
  current: FingerprintResult,
): StaleReasons;
export function fingerprintInputs(
  sourceFiles: readonly string[],
  extras?: readonly string[],
): Promise<FingerprintResult>;
export function toAppsRelative(file: string): string;
export function captureAllRequested(argv?: readonly string[]): boolean;
