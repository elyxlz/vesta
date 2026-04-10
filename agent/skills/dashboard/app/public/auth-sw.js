// Service worker that injects the Authorization header into same-origin
// requests so browser-initiated loads (fonts from CSS, images, etc.)
// pass through vestad's auth middleware.

let token = null;

self.addEventListener("message", (e) => {
  if (e.data?.type === "set-token") {
    token = e.data.token;
  }
});

self.addEventListener("fetch", (e) => {
  if (!token) return;
  // Only intercept same-origin requests
  if (new URL(e.request.url).origin !== self.location.origin) return;
  // Already has auth — don't override
  if (e.request.headers.get("authorization")) return;

  const authed = new Request(e.request, {
    headers: new Headers(e.request.headers),
  });
  authed.headers.set("Authorization", `Bearer ${token}`);
  e.respondWith(fetch(authed));
});
