import type { Page } from "@playwright/test";
import { VISUAL_CONNECTION } from "./storage";

// The preload API contract, mirrored from apps/web/src/lib/native/types.ts:
// the harness compiles in the node tsconfig project, which does not include src/.
interface VestaNativeApi {
  platform: string;
  focusWindow(): Promise<void>;
  setTheme(theme: "light" | "dark"): void;
  openExternal(url: string): Promise<void>;
  storeRead(): Promise<unknown>;
  storeWrite(value: unknown): Promise<void>;
  storeClear(): Promise<void>;
  oauthStart(): Promise<number>;
  onOauthCallback(cb: (url: string) => void): () => void;
  oauthCancel(port: number): Promise<void>;
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

// Defines window.vestaNative before app code runs, so the app takes its real
// desktop path (.desktop, .vibrancy, data-platform, titlebar inset or custom
// window controls). Every method is inert; the store starts with the saved
// visual connection, which is where the desktop bridge reads it from.
export async function installNativeStub(
  page: Page,
  options: { platform?: "darwin" | "win32"; connection?: boolean } = {},
): Promise<void> {
  await page.addInitScript(
    ({ connection, platform }) => {
      // The app reads the user agent, not the bridge, for platform-specific
      // chrome such as keybind glyphs, so a Windows shell needs a Windows UA.
      if (platform === "win32") {
        Object.defineProperty(navigator, "userAgent", {
          get: () =>
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Electron/38.0.0 Safari/537.36",
        });
      }
      let stored: unknown = connection;
      const noop = (): void => undefined;
      const resolved = (): Promise<void> => Promise.resolve();
      window.vestaNative = {
        platform,
        focusWindow: resolved,
        setTheme: noop,
        openExternal: resolved,
        storeRead: () => Promise.resolve(stored),
        storeWrite: (value: unknown) => {
          stored = value;
          return Promise.resolve();
        },
        storeClear: () => {
          stored = null;
          return Promise.resolve();
        },
        oauthStart: () => Promise.resolve(0),
        onOauthCallback: () => noop,
        oauthCancel: resolved,
        onWindowFocus: () => noop,
        windowMinimize: resolved,
        windowToggleMaximize: resolved,
        windowClose: resolved,
        windowIsMaximized: () => Promise.resolve(false),
        onWindowMaximizedChange: () => noop,
      };
    },
    {
      connection: options.connection === false ? null : VISUAL_CONNECTION,
      platform: options.platform ?? "darwin",
    },
  );
}
