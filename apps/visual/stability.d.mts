export function grabUntilStable(
  grab: () => Promise<Buffer>,
  options?: { pollMs?: number; timeoutMs?: number; stableMs?: number },
): Promise<Buffer>;
