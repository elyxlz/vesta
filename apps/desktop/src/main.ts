import { BrowserWindow, Menu, app, ipcMain, nativeTheme, shell } from "electron";
import path from "node:path";
import { cancelLoopback, startLoopback } from "./oauth-loopback";
import { clearConnection, readConnection, writeConnection } from "./store";
import { createMainWindow, registerAppScheme, showMainWindow } from "./window";

registerAppScheme();

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  let mainWindow: BrowserWindow | null = null;
  let quitting = false;

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
      if (theme === "light" || theme === "dark") nativeTheme.themeSource = theme;
    });
    ipcMain.handle("open-external", (_event, url: unknown) => {
      if (typeof url === "string" && /^https?:\/\//.test(url))
        return shell.openExternal(url);
      throw new Error("openExternal only accepts http(s) urls");
    });
    ipcMain.handle("store:read", () => readConnection());
    ipcMain.handle("store:write", (_event, value: unknown) =>
      writeConnection(value),
    );
    ipcMain.handle("store:clear", () => clearConnection());
    ipcMain.handle("oauth:start", () =>
      startLoopback((url) => mainWindow?.webContents.send("oauth:callback", url)),
    );
    ipcMain.handle("oauth:cancel", (_event, port: unknown) => {
      if (typeof port === "number") cancelLoopback(port);
    });
  };

  app.on("second-instance", () => {
    if (mainWindow) showMainWindow(mainWindow);
  });

  app.on("before-quit", () => {
    quitting = true;
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
      if (process.platform === "darwin" && !quitting) {
        event.preventDefault();
        mainWindow?.hide();
      }
    });
    // Drift toward the latest release on our own: check on launch, download in the
    // background, install on the next quit. Packaged only (dev has no update feed).
    if (app.isPackaged) {
      void import("./updater.js")
        .then(({ checkForAppUpdate }) => checkForAppUpdate())
        .catch((err: unknown) => {
          console.error("app update check failed:", err);
        });
    }
  });
}
