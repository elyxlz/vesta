/**
 * Reduce a stored gateway url to the http(s) origin the app is allowed to talk
 * to, or null when it is not one. Consumers connect to this value or navigate to
 * it (the sync socket, the log routes, the dashboard iframe src), so a stored
 * `javascript:` url would run as script in the frame. Callers get the `URL`
 * parser's output back, never the stored text.
 */
export function parseGatewayUrl(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return null;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
  return parsed.href.replace(/\/+$/, "");
}
