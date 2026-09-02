// Wire contract duplicated in apps/web/src/lib/native/types.ts
// (VestaNativeApi), keep the two declarations identical.
import { contextBridge, ipcRenderer } from "electron";
import { CHANNEL } from "./channels";

type IpcListener = Parameters<typeof ipcRenderer.on>[1];

function subscribe(channel: string, listener: IpcListener): () => void {
  ipcRenderer.on(channel, listener);
  return () => {
    ipcRenderer.removeListener(channel, listener);
  };
}

contextBridge.exposeInMainWorld("vestaNative", {
  platform: process.platform,
  focusWindow: () => ipcRenderer.invoke(CHANNEL.focusWindow),
  setTheme: (theme: string) => {
    ipcRenderer.send(CHANNEL.setTheme, theme);
  },
  openExternal: (url: string) => ipcRenderer.invoke(CHANNEL.openExternal, url),
  getAppUpdate: () => ipcRenderer.invoke(CHANNEL.appUpdateCheck),
  downloadAppUpdate: () => ipcRenderer.invoke(CHANNEL.appUpdateDownload),
  onAppUpdateProgress: (cb: (percent: number) => void) =>
    subscribe(CHANNEL.appUpdateProgress, (_event, percent: number) => {
      cb(percent);
    }),
  installAppUpdate: () => ipcRenderer.invoke(CHANNEL.appUpdateInstall),
  storeRead: () => ipcRenderer.invoke(CHANNEL.storeRead),
  storeWrite: (value: unknown) => ipcRenderer.invoke(CHANNEL.storeWrite, value),
  storeClear: () => ipcRenderer.invoke(CHANNEL.storeClear),
  storeIsSecure: () => ipcRenderer.invoke(CHANNEL.storeIsSecure),
  recentStoreRead: () => ipcRenderer.invoke(CHANNEL.recentStoreRead),
  recentStoreWrite: (value: unknown) =>
    ipcRenderer.invoke(CHANNEL.recentStoreWrite, value),
  recentStoreClear: () => ipcRenderer.invoke(CHANNEL.recentStoreClear),
  oauthStart: () => ipcRenderer.invoke(CHANNEL.oauthStart),
  onOauthCallback: (cb: (url: string) => void) =>
    subscribe(CHANNEL.oauthCallback, (_event, url: string) => {
      cb(url);
    }),
  oauthCancel: (port: number) => ipcRenderer.invoke(CHANNEL.oauthCancel, port),
  readGeolocation: () => ipcRenderer.invoke(CHANNEL.geolocationRead),
  onWindowFocus: (cb: (focused: boolean) => void) =>
    subscribe(CHANNEL.windowFocus, (_event, focused: boolean) => {
      cb(focused);
    }),
  windowMinimize: () => ipcRenderer.invoke(CHANNEL.windowMinimize),
  windowToggleMaximize: () => ipcRenderer.invoke(CHANNEL.windowToggleMaximize),
  windowClose: () => ipcRenderer.invoke(CHANNEL.windowClose),
  windowIsMaximized: () => ipcRenderer.invoke(CHANNEL.windowIsMaximized),
  onWindowMaximizedChange: (cb: (maximized: boolean) => void) =>
    subscribe(CHANNEL.windowMaximized, (_event, maximized: boolean) => {
      cb(maximized);
    }),
  getOpenAtLogin: () => ipcRenderer.invoke(CHANNEL.loginItemGet),
  setOpenAtLogin: (enabled: boolean) =>
    ipcRenderer.invoke(CHANNEL.loginItemSet, enabled),
});
