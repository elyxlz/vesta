export type Platform = "macos" | "windows" | "linux" | "ios" | "android";

export function detectPlatform(): Platform {
  const ua = navigator.userAgent;
  if (ua.includes("Android")) return "android";
  if (ua.includes("iPhone") || ua.includes("iPad")) return "ios";
  if (ua.includes("Mac")) {
    if ("maxTouchPoints" in navigator && navigator.maxTouchPoints > 0)
      return "ios";
    return "macos";
  }
  if (ua.includes("Windows")) return "windows";
  return "linux";
}
