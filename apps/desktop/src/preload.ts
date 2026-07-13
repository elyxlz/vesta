// Wire contract duplicated in apps/web/src/lib/native/types.ts
// (VestaNativeApi), keep the two declarations identical.
import { contextBridge, ipcRenderer } from "electron";

function subscribe<T>(channel: string, cb: (payload: T) => void): () => void {
  const listener = (_event: Electron.IpcRendererEvent, payload: T) =>
    cb(payload);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld("vestaNative", {
  platform: process.platform,
  focusWindow: () => ipcRenderer.invoke("focus-window"),
  setTheme: (theme: string) => ipcRenderer.send("set-theme", theme),
  openExternal: (url: string) => ipcRenderer.invoke("open-external", url),
  storeRead: () => ipcRenderer.invoke("store:read"),
  storeWrite: (value: unknown) => ipcRenderer.invoke("store:write", value),
  storeClear: () => ipcRenderer.invoke("store:clear"),
  oauthStart: () => ipcRenderer.invoke("oauth:start"),
  onOauthCallback: (cb: (url: string) => void) =>
    subscribe<string>("oauth:callback", cb),
  oauthCancel: (port: number) => ipcRenderer.invoke("oauth:cancel", port),
  installUpdate: (version: string) =>
    ipcRenderer.invoke("update:install", version),
  onWindowFocus: (cb: (focused: boolean) => void) =>
    subscribe<boolean>("window-focus", cb),
});
