export const storeDirectory: string;
export const shotsDirectory: string;
export function platformShotsDirectory(
  platform: string,
  baseDirectory?: string,
): string;
export function atomicWriteFile(target: string, contents: string): Promise<void>;
export function putShot(
  platform: string,
  name: string,
  source: string | Buffer,
  baseDirectory?: string,
): Promise<void>;
export function shotEntries(
  baseDirectory?: string,
): Promise<
  Record<
    string,
    Record<
      string,
      { src: string; mtime: number; size?: { width: number; height: number } | null }
    >
  >
>;
export function pngSize(
  filePath: string,
): Promise<{ width: number; height: number } | null>;
export function shotDriftWarning(
  producedNames: Set<string>,
  scenarios: { screenshot: string }[],
): string;

export interface ShotRecord {
  fingerprint: string;
  sources: string[];
  hashes?: Record<string, string>;
  extras?: string;
}
export function shotRecordPath(
  platform: string,
  name: string,
  baseDirectory?: string,
): string;
export function putShotRecord(
  platform: string,
  name: string,
  record: ShotRecord,
  baseDirectory?: string,
): Promise<void>;
export function readShotRecord(
  platform: string,
  name: string,
  baseDirectory?: string,
): Promise<ShotRecord | null>;
export function shotIsFresh(
  platforms: readonly string[],
  name: string,
  fingerprint: string,
  baseDirectory?: string,
): Promise<boolean>;
