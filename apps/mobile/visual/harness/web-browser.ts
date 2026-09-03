// expo-web-browser without the system browser: a flow that would open one
// (a provider sign-in, a release link) resolves at once, so the app renders
// the state after the browser instead of an OS sheet the shot cannot fix.
export const WebBrowserPresentationStyle = {
  FULL_SCREEN: 0,
  PAGE_SHEET: 1,
  FORM_SHEET: 2,
  CURRENT_CONTEXT: 3,
  OVER_FULL_SCREEN: 4,
  OVER_CURRENT_CONTEXT: 5,
  POPOVER: 6,
  AUTOMATIC: 7,
} as const;

export function maybeCompleteAuthSession(): {
  type: "failed";
  message: string;
} {
  return { type: "failed", message: "visual fixture" };
}

export async function openBrowserAsync(): Promise<{ type: "dismiss" }> {
  return { type: "dismiss" };
}

export async function openAuthSessionAsync(): Promise<{ type: "dismiss" }> {
  return { type: "dismiss" };
}
