// Every IPC channel the preload invokes and the main process handles, named once so a typo on
// either side is a type error, and preload-parity.test.ts checks the two sets against this table.
export const CHANNEL = {
  focusWindow: "focus-window",
  setTheme: "set-theme",
  openExternal: "open-external",
  appUpdateCheck: "app-update:check",
  appUpdateDownload: "app-update:download",
  appUpdateProgress: "app-update:progress",
  appUpdateInstall: "app-update:install",
  storeRead: "store:read",
  storeWrite: "store:write",
  storeClear: "store:clear",
  storeIsSecure: "store:is-secure",
  recentStoreRead: "recent-store:read",
  recentStoreWrite: "recent-store:write",
  recentStoreClear: "recent-store:clear",
  oauthStart: "oauth:start",
  oauthCallback: "oauth:callback",
  oauthCancel: "oauth:cancel",
  geolocationRead: "geolocation:read",
  windowFocus: "window-focus",
  windowMinimize: "window:minimize",
  windowToggleMaximize: "window:toggle-maximize",
  windowClose: "window:close",
  windowIsMaximized: "window:is-maximized",
  windowMaximized: "window-maximized",
  loginItemGet: "login-item:get",
  loginItemSet: "login-item:set",
} as const;

// Channels the main process pushes to the renderer (webContents.send); every other channel is
// invoked or sent by the renderer and handled in main.
export const PUSH_CHANNELS: readonly string[] = [
  CHANNEL.appUpdateProgress,
  CHANNEL.oauthCallback,
  CHANNEL.windowFocus,
  CHANNEL.windowMaximized,
];
