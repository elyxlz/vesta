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
  /** Converge the app onto the gateway's exact version. */
  installAppUpdate(version: string): Promise<void>;
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
  storeRead(): Promise<unknown>;
  storeWrite(value: unknown): Promise<void>;
  storeClear(): Promise<void>;
  oauthStart(): Promise<number>;
  onOauthCallback(cb: (url: string) => void): () => void;
  oauthCancel(port: number): Promise<void>;
  installUpdate(version: string): Promise<void>;
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
