import * as Linking from "expo-linking";

// The one reader of the launch URL's visual switches. Every fixture module
// reads its switch here, so the query is parsed once and a value is either
// the string the flow passed or null.
const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;

export function visualSwitch(name: string): string | null {
  const value = query?.[name];
  return typeof value === "string" ? value : null;
}

// A delay in ms the flow asks the fixtures to hold pending answers for, so a
// loading or in-flight state stays on screen long enough to capture.
export const visualDelayMs = Number(visualSwitch("visualDelay") ?? 0);

export function visualDelay(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, visualDelayMs));
}

// visualWhatsNewSeen=<version> seeds the last-seen release marker before the
// app mounts, so the release notes auto-open the way they do after an update.
export const WHATS_NEW_LAST_SEEN_KEY = "vesta.whats-new-last-seen.v1";
