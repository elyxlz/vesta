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
): Promise<Record<string, Record<string, { src: string; mtime: number }>>>;
export function pngSize(
  filePath: string,
): Promise<{ width: number; height: number } | null>;
export function shotDriftWarning(
  producedNames: Set<string>,
  scenarios: { screenshot: string }[],
): string;
