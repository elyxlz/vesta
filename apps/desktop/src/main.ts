import {
  BrowserWindow,
  Menu,
  app,
  ipcMain,
  nativeTheme,
  shell,
} from "electron";
import path from "node:path";
import { CHANNEL } from "./channels";
import { readNativeGeolocation } from "./geolocation";
import { trackQuitIntent } from "./lifecycle";
import { cancelLoopback, startLoopback } from "./oauth-loopback";
import {
  clearConnection,
  clearRecentGateways,
  credentialStorageIsSecure,
  readConnection,
  readRecentGateways,
  writeConnection,
  writeRecentGateways,
} from "./store";
import {
  downloadAppUpdate,
  getAppUpdate,
  quitAndInstallUpdate,
} from "./updater";
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
    ipcMain.handle(CHANNEL.focusWindow, () => {
      if (mainWindow) showMainWindow(mainWindow);
    });
    ipcMain.handle(CHANNEL.windowMinimize, () => mainWindow?.minimize());
    ipcMain.handle(CHANNEL.windowToggleMaximize, () => {
      if (!mainWindow) return;
      if (mainWindow.isMaximized()) mainWindow.unmaximize();
      else mainWindow.maximize();
    });
    ipcMain.handle(CHANNEL.windowClose, () => mainWindow?.close());
    ipcMain.handle(
      CHANNEL.windowIsMaximized,
      () => mainWindow?.isMaximized() ?? false,
    );
    ipcMain.on(CHANNEL.setTheme, (_event, theme: unknown) => {
      // "system" hands the scheme back to the OS, so prefers-color-scheme in the renderer tracks it
      // again instead of the last forced value.
      if (theme === "light" || theme === "dark" || theme === "system")
        nativeTheme.themeSource = theme;
    });
    ipcMain.handle(CHANNEL.openExternal, (_event, url: unknown) => {
      if (typeof url === "string" && /^https?:\/\//.test(url))
        return shell.openExternal(url);
      throw new Error("openExternal only accepts http(s) urls");
    });
    // App self-update is manual: the renderer drives check -> download -> relaunch on a click.
    ipcMain.handle(CHANNEL.appUpdateCheck, () => getAppUpdate());
    ipcMain.handle(CHANNEL.appUpdateDownload, (event) =>
      downloadAppUpdate((percent) => {
        event.sender.send(CHANNEL.appUpdateProgress, percent);
      }),
    );
    ipcMain.handle(CHANNEL.appUpdateInstall, () => {
      quitAndInstallUpdate();
    });
    ipcMain.handle(CHANNEL.storeRead, () => readConnection());
    ipcMain.handle(CHANNEL.storeWrite, (_event, value: unknown) =>
      writeConnection(value),
    );
    ipcMain.handle(CHANNEL.storeClear, () => clearConnection());
    ipcMain.handle(CHANNEL.storeIsSecure, () => credentialStorageIsSecure());
    ipcMain.handle(CHANNEL.recentStoreRead, () => readRecentGateways());
    ipcMain.handle(CHANNEL.recentStoreWrite, (_event, value: unknown) =>
      writeRecentGateways(value),
    );
    ipcMain.handle(CHANNEL.recentStoreClear, () => clearRecentGateways());
    ipcMain.handle(CHANNEL.oauthStart, () =>
      startLoopback((url) =>
        mainWindow?.webContents.send(CHANNEL.oauthCallback, url),
      ),
    );
    ipcMain.handle(CHANNEL.oauthCancel, (_event, port: unknown) => {
      if (typeof port === "number") cancelLoopback(port);
    });
    // The macOS CoreLocation helper ships beside the web bundle in Resources; in dev it is the
    // `native/` build output.
    const macHelperPath = app.isPackaged
      ? path.join(process.resourcesPath, "vesta-location")
      : path.join(app.getAppPath(), "native", "vesta-location");
    ipcMain.handle(CHANNEL.geolocationRead, () =>
      readNativeGeolocation(macHelperPath),
    );
    // OS launch-at-login toggle; the login item is the source of truth (registry on Windows,
    // LaunchAgent on macOS, ~/.config/autostart on Linux), so nothing is persisted here.
    ipcMain.handle(
      CHANNEL.loginItemGet,
      () => app.getLoginItemSettings().openAtLogin,
    );
    ipcMain.handle(CHANNEL.loginItemSet, (_event, enabled: unknown) => {
      app.setLoginItemSettings({ openAtLogin: enabled === true });
    });
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
