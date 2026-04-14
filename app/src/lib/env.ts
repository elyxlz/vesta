declare const __TAURI__: boolean;
declare const __PLATFORM__: string;

export const isTauri: boolean =
  typeof __TAURI__ !== "undefined" && __TAURI__
    ? true
    : typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export const buildPlatform: string =
  typeof __PLATFORM__ !== "undefined" ? __PLATFORM__ : "";
