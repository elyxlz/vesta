let authToken: string | null = null;
let baseUrl: string | null = null;
let _resolveAuth: (() => void) | null = null;
const _authReady = new Promise<void>((r) => { _resolveAuth = r; });
let _fullscreen = false;
const _layoutListeners: Set<(fullscreen: boolean) => void> = new Set();

export function isFullscreen(): boolean {
  return _fullscreen;
}

export function onLayoutChange(cb: (fullscreen: boolean) => void): () => void {
  _layoutListeners.add(cb);
  return () => _layoutListeners.delete(cb);
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
      document.documentElement.classList.toggle("dark", event.data.dark);
    }
    if (event.data?.type === "vesta-auth") {
      authToken = event.data.token;
      baseUrl = event.data.baseUrl;
      _resolveAuth?.();
      registerSW();
    }
    if (event.data?.type === "vesta-layout") {
      _fullscreen = !!event.data.fullscreen;
      _layoutListeners.forEach((cb) => cb(_fullscreen));
    }
  });

  window.parent.postMessage({ type: "vesta-theme-request" }, "*");
  window.parent.postMessage({ type: "vesta-auth-request" }, "*");
  window.parent.postMessage({ type: "vesta-layout-request" }, "*");

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("controllerchange", () => sendTokenToSW());
  }
}

let _swRegistered = false;

function registerSW() {
  if (_swRegistered || !authToken || !("serviceWorker" in navigator)) return;
  _swRegistered = true;
  // Pass token so the SW script itself passes auth.
  navigator.serviceWorker
    .register(`./auth-sw.js?token=${encodeURIComponent(authToken)}`)
    .then(() => sendTokenToSW());
}

function sendTokenToSW() {
  const sw = navigator.serviceWorker?.controller;
  if (sw && authToken) {
    sw.postMessage({ type: "set-token", token: authToken });
  }
}
