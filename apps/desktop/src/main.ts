import {
  BrowserWindow,
  Menu,
  app,
  ipcMain,
  nativeTheme,
  shell,
} from "electron";
import path from "node:path";
import { readNativeGeolocation } from "./geolocation";
import { trackQuitIntent } from "./lifecycle";
import { cancelLoopback, startLoopback } from "./oauth-loopback";
import {
  clearConnection,
  clearRecentGateways,
  readConnection,
  readRecentGateways,
  writeConnection,
  writeRecentGateways,
} from "./store";
import { createMainWindow, registerAppScheme, showMainWindow } from "./window";

registerAppScheme();

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  let mainWindow: BrowserWindow | null = null;
  const isQuitting = trackQuitIntent(app);

  const buildMenu = () => {
    if (process.platform !== "darwin") {
      Menu.setApplicationMenu(null);
      return;
    }
    // No View menu: zoom accelerators stay disabled, matching the old app.
    Menu.setApplicationMenu(
      Menu.buildFromTemplate([
        { role: "appMenu" },
        { role: "editMenu" },
        { role: "windowMenu" },
      ]),
    );
  };

  const wireIpc = () => {
    ipcMain.handle("focus-window", () => {
      if (mainWindow) showMainWindow(mainWindow);
    });
    ipcMain.handle("window:minimize", () => mainWindow?.minimize());
    ipcMain.handle("window:toggle-maximize", () => {
      if (!mainWindow) return;
      if (mainWindow.isMaximized()) mainWindow.unmaximize();
      else mainWindow.maximize();
    });
    ipcMain.handle("window:close", () => mainWindow?.close());
    ipcMain.handle(
      "window:is-maximized",
      () => mainWindow?.isMaximized() ?? false,
    );
    ipcMain.on("set-theme", (_event, theme: unknown) => {
      // "system" hands the scheme back to the OS, so prefers-color-scheme in the renderer tracks it
      // again instead of the last forced value.
      if (theme === "light" || theme === "dark" || theme === "system")
        nativeTheme.themeSource = theme;
    });
    ipcMain.handle("open-external", (_event, url: unknown) => {
      if (typeof url === "string" && /^https?:\/\//.test(url))
        return shell.openExternal(url);
      throw new Error("openExternal only accepts http(s) urls");
    });
    // App self-update is manual: the renderer drives check -> download -> relaunch on a click.
    ipcMain.handle("app-update:check", () =>
      import("./updater.js").then(({ getAppUpdate }) => getAppUpdate()),
    );
    ipcMain.handle("app-update:download", (event) =>
      import("./updater.js").then(({ downloadAppUpdate }) =>
        downloadAppUpdate((percent) => {
          event.sender.send("app-update:progress", percent);
        }),
      ),
    );
    ipcMain.handle("app-update:install", () =>
      import("./updater.js").then(({ quitAndInstallUpdate }) =>
        quitAndInstallUpdate(),
      ),
    );
    ipcMain.handle("store:read", () => readConnection());
    ipcMain.handle("store:write", (_event, value: unknown) =>
      writeConnection(value),
    );
    ipcMain.handle("store:clear", () => clearConnection());
    ipcMain.handle("recent-store:read", () => readRecentGateways());
    ipcMain.handle("recent-store:write", (_event, value: unknown) =>
      writeRecentGateways(value),
    );
    ipcMain.handle("recent-store:clear", () => clearRecentGateways());
    ipcMain.handle("oauth:start", () =>
      startLoopback((url) =>
        mainWindow?.webContents.send("oauth:callback", url),
      ),
    );
    ipcMain.handle("oauth:cancel", (_event, port: unknown) => {
      if (typeof port === "number") cancelLoopback(port);
    });
    // The macOS CoreLocation helper ships beside the web bundle in Resources; in dev it is the
    // `native/` build output.
    const macHelperPath = app.isPackaged
      ? path.join(process.resourcesPath, "vesta-location")
      : path.join(app.getAppPath(), "native", "vesta-location");
    ipcMain.handle("geolocation:read", () =>
      readNativeGeolocation(macHelperPath),
    );
  };

  app.on("second-instance", () => {
    if (mainWindow) showMainWindow(mainWindow);
  });

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });

  app.on("activate", () => {
    if (mainWindow) showMainWindow(mainWindow);
  });

  void app.whenReady().then(() => {
    // Packaged builds get the icon from electron-builder; set it explicitly so
    // the dock icon is Vesta in `npm run dev` too (raw electron shows its own).
    if (process.platform === "darwin" && !app.isPackaged) {
      app.dock?.setIcon(path.join(__dirname, "..", "build", "icon.png"));
    }
    buildMenu();
    wireIpc();
    mainWindow = createMainWindow();
    // macOS convention: closing the window keeps Vesta in the dock.
    mainWindow.on("close", (event) => {
      if (process.platform === "darwin" && !isQuitting()) {
        event.preventDefault();
        mainWindow?.hide();
      }
    });
  });
}
