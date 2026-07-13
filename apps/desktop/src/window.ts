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
      vibrancy: "hud" as const,
      visualEffectState: "active" as const,
      acceptFirstMouse: true,
    }),
    ...(process.platform === "win32" && {
      titleBarStyle: "hidden" as const,
      titleBarOverlay: true,
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

  const sendFocus = (focused: boolean) => () =>
    window.webContents.send("window-focus", focused);
  window.on("focus", sendFocus(true));
  window.on("blur", sendFocus(false));

  void window.loadURL(DEV_SERVER_URL ?? `${APP_ORIGIN}/`);
  return window;
}

export function showMainWindow(window: BrowserWindow): void {
  window.show();
  if (window.isMinimized()) window.restore();
  window.focus();
}
