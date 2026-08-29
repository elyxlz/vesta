import { native } from "./native";

// A stable per-install id (minted once, persisted) plus a self-composed label, reported up /sync so
// vestad tracks this device in the registry. Mirrors mobile's installation id.
const INSTALLATION_ID_KEY = "vesta.installation-id.v1";

function installationId(): string {
  try {
    const existing = localStorage.getItem(INSTALLATION_ID_KEY);
    if (existing !== null && existing !== "") return existing;
    const minted = crypto.randomUUID();
    localStorage.setItem(INSTALLATION_ID_KEY, minted);
    return minted;
  } catch {
    // Storage unavailable (private mode): a fresh id each session is unstable but never fatal.
    return crypto.randomUUID();
  }
}

function osName(ua: string): string {
  if (ua.includes("Windows")) return "Windows";
  if (/Mac OS X|Macintosh/.test(ua)) return "macOS";
  if (ua.includes("Android")) return "Android";
  if (/iPhone|iPad|iPod/.test(ua)) return "iOS";
  if (ua.includes("Linux")) return "Linux";
  return "an unknown OS";
}

function browserName(ua: string): string {
  if (ua.includes("Edg/")) return "Edge";
  if (/OPR\/|Opera/.test(ua)) return "Opera";
  if (ua.includes("Firefox/")) return "Firefox";
  if (ua.includes("Chrome/")) return "Chrome";
  if (ua.includes("Safari/")) return "Safari";
  return "a browser";
}

export function deviceIdentity(): { id: string; descriptor: string } {
  const ua = navigator.userAgent;
  const os = osName(ua);
  const surface =
    native.runtime === "electron" ? "Vesta desktop" : browserName(ua);
  return { id: installationId(), descriptor: `${surface} on ${os}` };
}
