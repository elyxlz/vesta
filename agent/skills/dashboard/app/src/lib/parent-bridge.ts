let authToken: string | null = null;
let baseUrl: string | null = null;

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
export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  if (!baseUrl) throw new Error("Dashboard not connected to parent app yet");
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
    }
  });

  window.parent.postMessage({ type: "vesta-theme-request" }, "*");
  window.parent.postMessage({ type: "vesta-auth-request" }, "*");
}
