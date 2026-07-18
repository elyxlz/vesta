let authToken: string | null = null;
let baseUrl: string | null = null;
let _agentName: string | null = null;
let _resolveAuth: (() => void) | null = null;
const _authReady = new Promise<void>((r) => { _resolveAuth = r; });
let _fullscreen = false;
const _layoutListeners: Set<(fullscreen: boolean) => void> = new Set();

declare global {
  interface Window {
    ReactNativeWebView?: { postMessage: (message: string) => void };
  }
}

function postToParent(message: { type: string }): void {
  window.parent.postMessage(message, "*");
  window.ReactNativeWebView?.postMessage(JSON.stringify(message));
}

export interface PlatformInfo {
  isDesktopApp: boolean;
  platform: string;
  isDesktop: boolean;
  isMobile: boolean;
  vibrancy: boolean;
}

let _platform: PlatformInfo = {
  isDesktopApp: false,
  platform: "unknown",
  isDesktop: false,
  isMobile: false,
  vibrancy: false,
};
const _platformListeners: Set<(info: PlatformInfo) => void> = new Set();

export function getPlatform(): PlatformInfo {
  return _platform;
}

export function onPlatformChange(cb: (info: PlatformInfo) => void): () => void {
  _platformListeners.add(cb);
  return () => _platformListeners.delete(cb);
}

export function isFullscreen(): boolean {
  return _fullscreen;
}

export function onLayoutChange(cb: (fullscreen: boolean) => void): () => void {
  _layoutListeners.add(cb);
  return () => _layoutListeners.delete(cb);
}

export function getAgentName(): string | null {
  return _agentName;
}

export function waitForAuth(): Promise<void> {
  return _authReady;
}

export function getAuthToken(): string | null {
  return authToken;
}

export function authHeaders(): Record<string, string> {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {};
}

/**
 * Fetch a skill endpoint with auth.
 * Usage: apiFetch("tasks/list") or apiFetch("voice/tts/status")
 */
export async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  await _authReady;
  const url = `${baseUrl}/${path.replace(/^\//, "")}`;
  return fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...init?.headers },
  });
}

export function initParentBridge() {
  window.addEventListener("message", (event) => {
    if (event.data?.type === "vesta-theme") {
      const dark = !!event.data.dark;
      document.documentElement.classList.toggle("dark", dark);
      document.documentElement.style.colorScheme = dark ? "dark" : "light";
    }
    if (event.data?.type === "vesta-auth") {
      authToken = event.data.token;
      baseUrl = event.data.baseUrl;
      _agentName = event.data.agentName ?? null;
      _resolveAuth?.();
    }
    if (event.data?.type === "vesta-layout") {
      _fullscreen = !!event.data.fullscreen;
      _layoutListeners.forEach((cb) => cb(_fullscreen));
    }
    if (event.data?.type === "vesta-platform") {
      _platform = {
        isDesktopApp: !!event.data.isDesktopApp,
        platform: event.data.platform ?? "unknown",
        isDesktop: !!event.data.isDesktop,
        isMobile: !!event.data.isMobile,
        vibrancy: !!event.data.vibrancy,
      };
      document.documentElement.classList.toggle(
        "desktop",
        _platform.isDesktopApp,
      );
      document.documentElement.classList.toggle("vibrancy", _platform.vibrancy);
      _platformListeners.forEach((cb) => cb(_platform));
    }
  });

  postToParent({ type: "vesta-theme-request" });
  postToParent({ type: "vesta-auth-request" });
  postToParent({ type: "vesta-layout-request" });
  postToParent({ type: "vesta-platform-request" });
}
