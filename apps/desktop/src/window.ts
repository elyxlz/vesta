import { BrowserWindow, app, net, protocol, session, shell } from "electron";
import path from "node:path";
import { pathToFileURL } from "node:url";

export const APP_SCHEME = "vesta";
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

/** Serve the bundled SPA with an index.html fallback so client-side routes deep-link. */
function handleAppProtocol(): void {
  const webDist = app.isPackaged
    ? path.join(process.resourcesPath, "web")
    : path.join(app.getAppPath(), "..", "web", "dist");

  protocol.handle(APP_SCHEME, (request) => {
    const { pathname } = new URL(request.url);
    const resolved = path.normalize(
      path.join(webDist, decodeURIComponent(pathname)),
    );
    const target =
      resolved.startsWith(webDist) && path.extname(resolved) !== ""
        ? resolved
        : path.join(webDist, "index.html");
    return net.fetch(pathToFileURL(target).toString());
  });
}

function allowMicrophoneOnly(): void {
  session.defaultSession.setPermissionRequestHandler(
    (_wc, permission, callback) => {
      callback(permission === "media");
    },
  );
}

export function createMainWindow(): BrowserWindow {
  handleAppProtocol();
  allowMicrophoneOnly();

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
    window.webContents.send("window-focus", focused);
  };
  window.on("focus", sendFocus(true));
  window.on("blur", sendFocus(false));

  const sendMax = (maximized: boolean) => () => {
    window.webContents.send("window-maximized", maximized);
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
