// Wire contract duplicated in apps/web/src/lib/native/types.ts
// (VestaNativeApi), keep the two declarations identical.
import { contextBridge, ipcRenderer } from "electron";

type IpcListener = Parameters<typeof ipcRenderer.on>[1];

function subscribe(channel: string, listener: IpcListener): () => void {
  ipcRenderer.on(channel, listener);
  return () => {
    ipcRenderer.removeListener(channel, listener);
  };
}

contextBridge.exposeInMainWorld("vestaNative", {
  platform: process.platform,
  focusWindow: () => ipcRenderer.invoke("focus-window"),
  setTheme: (theme: string) => {
    ipcRenderer.send("set-theme", theme);
  },
  openExternal: (url: string) => ipcRenderer.invoke("open-external", url),
  storeRead: () => ipcRenderer.invoke("store:read"),
  storeWrite: (value: unknown) => ipcRenderer.invoke("store:write", value),
  storeClear: () => ipcRenderer.invoke("store:clear"),
  oauthStart: () => ipcRenderer.invoke("oauth:start"),
  onOauthCallback: (cb: (url: string) => void) =>
    subscribe("oauth:callback", (_event, url: string) => {
      cb(url);
    }),
  oauthCancel: (port: number) => ipcRenderer.invoke("oauth:cancel", port),
  installUpdate: (version: string) =>
    ipcRenderer.invoke("update:install", version),
  onWindowFocus: (cb: (focused: boolean) => void) =>
    subscribe("window-focus", (_event, focused: boolean) => {
      cb(focused);
    }),
  windowMinimize: () => ipcRenderer.invoke("window:minimize"),
  windowToggleMaximize: () => ipcRenderer.invoke("window:toggle-maximize"),
  windowClose: () => ipcRenderer.invoke("window:close"),
  windowIsMaximized: () => ipcRenderer.invoke("window:is-maximized"),
  onWindowMaximizedChange: (cb: (maximized: boolean) => void) =>
    subscribe("window-maximized", (_event, maximized: boolean) => {
      cb(maximized);
    }),
});
