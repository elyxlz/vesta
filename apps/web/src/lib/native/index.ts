import { createBrowserBridge } from "./browser";
import { createElectronBridge } from "./electron";
import type { NativeBridge } from "./types";

export type { NativeBridge, Runtime, VestaNativeApi } from "./types";

export const native: NativeBridge =
  typeof window !== "undefined" && window.vestaNative
    ? createElectronBridge(window.vestaNative)
    : createBrowserBridge();
