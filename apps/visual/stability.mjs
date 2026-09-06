// Pixel stability is independent of copy and component structure. A timeout
// is a capture failure, never permission to record an arbitrary final frame.
export async function grabUntilStable(grab, options = {}) {
  const pollMs = options.pollMs ?? 120;
  const timeoutMs = options.timeoutMs ?? 8_000;
  const stableMs = options.stableMs ?? 250;
  const deadline = Date.now() + timeoutMs;
  let previous = await grab();
  let stableSince = Date.now();
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, pollMs));
    const current = await grab();
    if (!current.equals(previous)) stableSince = Date.now();
    else if (Date.now() - stableSince >= stableMs) return current;
    previous = current;
  }
  throw new Error(`Screenshot did not settle within ${timeoutMs} ms.`);
}
