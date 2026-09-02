import {
  BrowserWindow,
  app,
  net,
  protocol,
  session,
  shell,
  systemPreferences,
} from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { CHANNEL } from "./channels";

const APP_SCHEME = "vesta";
const APP_ORIGIN = `${APP_SCHEME}://bundle`;
const DEV_SERVER_URL =
  process.env.VESTA_DESKTOP_DEV === "1" ? "http://localhost:1420" : null;

const WINDOW_WIDTH = 1200;
const WINDOW_HEIGHT = 750;
const WINDOW_MIN_SIZE = 380;
// Center the traffic lights on the navbar's content row (10px top padding +
// 40px row = center y=30; y eyeballed from there). The web-side geometry lives
// in one block in apps/web/src/index.css (:root.desktop[data-platform="macos"]);
// keep the two in sync.
const TRAFFIC_LIGHTS_POSITION = { x: 18, y: 23 };

export function registerAppScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: APP_SCHEME,
      privileges: { standard: true, secure: true, supportFetchAPI: true },
    },
  ]);
}

/**
 * The bundle file a request path maps to: null when the path escapes the bundle dir, and
 * index.html for any extension-less path so client-side routes deep-link.
 */
export function resolveBundlePath(
  webDist: string,
  pathname: string,
): string | null {
  const resolved = path.normalize(
    path.join(webDist, decodeURIComponent(pathname)),
  );
  const relative = path.relative(webDist, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return null;
  return path.extname(resolved) === ""
    ? path.join(webDist, "index.html")
    : resolved;
}

// The renderer renders agent-authored markdown and holds the gateway tokens the preload hands
// out, so script may only come from the bundle. The gateway itself may be a plain-http LAN
// origin, hence http(s) and ws(s) in connect, frame, media, and image sources.
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https: http:",
  "media-src 'self' blob: https: http:",
  "connect-src 'self' https: wss: http: ws:",
  "frame-src https: http:",
  "font-src 'self' data:",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
].join("; ");

/** The bundle response with the app's Content-Security-Policy stamped on it. */
export function withContentSecurityPolicy(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Content-Security-Policy", CONTENT_SECURITY_POLICY);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

/** Serve the bundled SPA with an index.html fallback so client-side routes deep-link. */
function handleAppProtocol(): void {
  const webDist = app.isPackaged
    ? path.join(process.resourcesPath, "web")
    : path.join(app.getAppPath(), "..", "web", "dist");

  protocol.handle(APP_SCHEME, async (request) => {
    const { pathname } = new URL(request.url);
    const target =
      resolveBundlePath(webDist, pathname) ?? path.join(webDist, "index.html");
    return withContentSecurityPolicy(
      await net.fetch(pathToFileURL(target).toString()),
    );
  });
}

// Microphone (voice) and geolocation (the "share this device's location" opt-in) are the only
// permissions the renderer may request; everything else, the camera included, is denied.
export function rendererPermissionDecision(
  permission: string,
  mediaTypes: readonly string[] | undefined,
): "grant" | "media" | "deny" {
  if (permission === "geolocation") return "grant";
  if (permission === "media") {
    const audioOnly =
      mediaTypes !== undefined &&
      mediaTypes.length > 0 &&
      mediaTypes.every((type) => type === "audio");
    return audioOnly ? "media" : "deny";
  }
  return "deny";
}

function allowRendererPermissions(): void {
  session.defaultSession.setPermissionRequestHandler(
    (_wc, permission, callback, details) => {
      const decision = rendererPermissionDecision(
        permission,
        "mediaTypes" in details ? details.mediaTypes : undefined,
      );
      if (decision !== "media") {
        callback(decision === "grant");
        return;
      }
      // The hardened-runtime entitlement lets the app reach the microphone; this obtains the
      // OS grant (the TCC prompt) that Chromium's getUserMedia needs on top of it. macOS only;
      // other platforms gate on the renderer callback alone.
      if (process.platform !== "darwin") {
        callback(true);
        return;
      }
      void systemPreferences.askForMediaAccess("microphone").then(
        (granted) => {
          callback(granted);
        },
        () => {
          callback(false);
        },
      );
    },
  );
}

/** Where a renderer-triggered download (a chat attachment blob) lands by default. */
export function downloadDefaultPath(
  downloadsDir: string,
  filename: string,
): string {
  return path.join(downloadsDir, filename || "file");
}

// Chat attachment downloads come through as renderer blob anchors; keep the native
// save dialog but preselect the OS Downloads folder under the attachment's name.
function routeDownloadsToDisk(): void {
  session.defaultSession.on("will-download", (_event, item) => {
    item.setSaveDialogOptions({
      defaultPath: downloadDefaultPath(
        app.getPath("downloads"),
        item.getFilename(),
      ),
    });
  });
}

export function createMainWindow(): BrowserWindow {
  handleAppProtocol();
  allowRendererPermissions();
  routeDownloadsToDisk();

  const window = new BrowserWindow({
    title: "Vesta",
    width: WINDOW_WIDTH,
    height: WINDOW_HEIGHT,
    minWidth: WINDOW_MIN_SIZE,
    minHeight: WINDOW_MIN_SIZE,
    show: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      backgroundThrottling: false,
    },
    ...(process.platform === "darwin" && {
      titleBarStyle: "hiddenInset" as const,
      trafficLightPosition: TRAFFIC_LIGHTS_POSITION,
      // under-window is the native main-window glass (the base layer beneath
      // window content); followWindow dims it when the window is inactive. No
      // transparent backgroundColor: it would switch the window to Electron's
      // transparent path and override the native squircle corner radius.
      vibrancy: "under-window" as const,
      visualEffectState: "followWindow" as const,
      acceptFirstMouse: true,
    }),
    ...(process.platform === "win32" && {
      // Hidden title bar with no OS caption buttons (no titleBarOverlay); the
      // app draws its own min/max/close (see components/WindowControls). Keeps
      // the resizable frame + Mica backdrop.
      titleBarStyle: "hidden" as const,
      backgroundMaterial: "mica" as const,
    }),
  });

  // External links only ever open in the system browser; the SPA is single-window.
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://") || url.startsWith("http://"))
      void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    const allowed = DEV_SERVER_URL
      ? url.startsWith(DEV_SERVER_URL)
      : url.startsWith(APP_ORIGIN);
    if (!allowed) event.preventDefault();
  });

  const sendFocus = (focused: boolean) => () => {
    window.webContents.send(CHANNEL.windowFocus, focused);
  };
  window.on("focus", sendFocus(true));
  window.on("blur", sendFocus(false));

  const sendMax = (maximized: boolean) => () => {
    window.webContents.send(CHANNEL.windowMaximized, maximized);
  };
  window.on("maximize", sendMax(true));
  window.on("unmaximize", sendMax(false));

  void window.loadURL(DEV_SERVER_URL ?? `${APP_ORIGIN}/`);
  return window;
}

export function showMainWindow(window: BrowserWindow): void {
  window.show();
  if (window.isMinimized()) window.restore();
  window.focus();
}
