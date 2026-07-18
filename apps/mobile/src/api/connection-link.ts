export type ConnectLinkResult =
  | { ok: true; url: string; key: string }
  | { ok: false; message: string };

function isPrivateIpv4(hostname: string): boolean {
  const parts = hostname.split(".").map(Number);
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part))) {
    return false;
  }
  const first = parts[0];
  const second = parts[1];
  if (first === undefined || second === undefined) return false;
  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 168)
  );
}

function isPrivateHost(hostname: string): boolean {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    normalized === "localhost" ||
    normalized.endsWith(".localhost") ||
    normalized.endsWith(".local") ||
    normalized === "::1" ||
    normalized.startsWith("fe80:") ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    isPrivateIpv4(normalized)
  );
}

export function parseConnectLink(input: string): ConnectLinkResult {
  const trimmed = input.trim();
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return {
      ok: false,
      message: "Paste the complete connection link shown by vestad.",
    };
  }

  const key = new URLSearchParams(parsed.hash.slice(1)).get("k")?.trim();
  if (!key) {
    return { ok: false, message: "This connection link has no key." };
  }
  if (parsed.protocol !== "https:") {
    return {
      ok: false,
      message: "Mobile connections require a trusted HTTPS tunnel.",
    };
  }
  if (isPrivateHost(parsed.hostname)) {
    return {
      ok: false,
      message: "Direct LAN pairing is not supported. Use a public HTTPS tunnel.",
    };
  }

  return { ok: true, url: parsed.origin, key };
}
