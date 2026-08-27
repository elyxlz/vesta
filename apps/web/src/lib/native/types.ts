import type { ConnectionConfig } from "@/lib/connection";
import type { Platform } from "@/lib/platform";

export type Runtime = "electron" | "browser";

export interface ConnectionStore {
  read(): Promise<ConnectionConfig | null>;
  write(config: ConnectionConfig): Promise<void>;
  clear(): Promise<void>;
}

export interface OauthLoopback {
  /** Start the loopback HTTP server; resolves with the bound port. */
  start(): Promise<number>;
  /** Subscribe to redirect hits; returns an unsubscribe function. */
  onCallback(cb: (url: string) => void): () => void;
  cancel(port: number): Promise<void>;
}

// A fix the desktop main process resolved through the OS location provider (WinRT on Windows,
// GeoClue2 on Linux); macOS answers null and the renderer's own geolocation covers it.
export interface NativeGeolocationFix {
  latitude: number;
  longitude: number;
  accuracyM: number | null;
}

// The latest stable release relative to the running desktop app, resolved on demand.
export interface AppUpdateStatus {
  available: boolean;
  version: string | null;
}

// Manual desktop self-update: the App Settings Updates card and the AppBehindScreen drive
// check -> download -> relaunch on a click, so the app never silently runs ahead of the gateway.
export interface AppUpdater {
  check(): Promise<AppUpdateStatus>;
  download(onProgress: (percent: number) => void): Promise<void>;
  install(): Promise<void>;
}

export interface WindowControls {
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  close(): Promise<void>;
  isMaximized(): Promise<boolean>;
  /** Maximize/unmaximize events; returns an unsubscribe function. */
  onMaximizedChange(cb: (maximized: boolean) => void): () => void;
}

export interface NativeBridge {
  runtime: Runtime;
  platform: Platform;
  connectionStore: ConnectionStore;
  openExternal(url: string): Promise<void>;
  focusWindow(): Promise<void>;
  setNativeTheme(theme: "light" | "dark"): void;
  /** Native window focus/blur events; returns an unsubscribe function. */
  onWindowFocusChange(cb: (focused: boolean) => void): () => void;
  /** Loopback server for the native PKCE login; null in the browser. */
  oauthLoopback: OauthLoopback | null;
  /** Custom title-bar controls; null when the OS draws them (browser, macOS). */
  windowControls: WindowControls | null;
  /** OS geolocation resolved by the desktop main process; null in the browser. */
  readGeolocation: (() => Promise<NativeGeolocationFix | null>) | null;
  /** Manual desktop self-update, driven by the App Settings Updates card; null in the browser. */
  appUpdate: AppUpdater | null;
}

/**
 * The preload API the Electron main process exposes. Wire contract duplicated
 * in apps/desktop/src/preload.ts, keep the two declarations identical.
 */
export interface VestaNativeApi {
  platform: string; // node process.platform: "darwin" | "win32" | "linux"
  focusWindow(): Promise<void>;
  setTheme(theme: "light" | "dark"): void;
  openExternal(url: string): Promise<void>;
  getAppUpdate(): Promise<unknown>;
  downloadAppUpdate(): Promise<void>;
  onAppUpdateProgress(cb: (percent: number) => void): () => void;
  installAppUpdate(): Promise<void>;
  storeRead(): Promise<unknown>;
  storeWrite(value: unknown): Promise<void>;
  storeClear(): Promise<void>;
  oauthStart(): Promise<number>;
  onOauthCallback(cb: (url: string) => void): () => void;
  oauthCancel(port: number): Promise<void>;
  readGeolocation(): Promise<unknown>;
  onWindowFocus(cb: (focused: boolean) => void): () => void;
  windowMinimize(): Promise<void>;
  windowToggleMaximize(): Promise<void>;
  windowClose(): Promise<void>;
  windowIsMaximized(): Promise<boolean>;
  onWindowMaximizedChange(cb: (maximized: boolean) => void): () => void;
}

declare global {
  interface Window {
    vestaNative?: VestaNativeApi;
  }
}
