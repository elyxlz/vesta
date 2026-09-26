import { screen, type BrowserWindow, type Rectangle } from "electron";
import { readWindowState, writeWindowState } from "./store";

// resize and move fire continuously during a drag; write once the gesture settles.
const SAVE_DEBOUNCE_MS = 500;
// A restored window must show at least this much of itself on some display.
const MIN_VISIBLE_PX = 80;

export interface WindowState {
  bounds: Rectangle;
  maximized: boolean;
}

function isRectangle(value: unknown): value is Rectangle {
  return (
    value !== null &&
    typeof value === "object" &&
    "x" in value &&
    Number.isFinite(value.x) &&
    "y" in value &&
    Number.isFinite(value.y) &&
    "width" in value &&
    Number.isFinite(value.width) &&
    "height" in value &&
    Number.isFinite(value.height)
  );
}

export function parseWindowState(value: unknown): WindowState | null {
  if (value === null || typeof value !== "object") return null;
  if (!("bounds" in value) || !isRectangle(value.bounds)) return null;
  if (!("maximized" in value) || typeof value.maximized !== "boolean") {
    return null;
  }
  return { bounds: value.bounds, maximized: value.maximized };
}

function overlap(
  a: Rectangle,
  b: Rectangle,
): { width: number; height: number } {
  return {
    width: Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x),
    height: Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y),
  };
}

/** Whether the saved bounds still land on a connected display (a monitor may be gone). */
export function isOnScreen(bounds: Rectangle, workAreas: Rectangle[]): boolean {
  return workAreas.some((area) => {
    const { width, height } = overlap(bounds, area);
    return width >= MIN_VISIBLE_PX && height >= MIN_VISIBLE_PX;
  });
}

export async function loadWindowState(): Promise<WindowState | null> {
  const state = parseWindowState(await readWindowState());
  if (!state) return null;
  const workAreas = screen.getAllDisplays().map((display) => display.workArea);
  return isOnScreen(state.bounds, workAreas) ? state : null;
}

/** Persist the window's normal bounds and maximized flag whenever either changes. */
export function trackWindowState(window: BrowserWindow): void {
  let timer: NodeJS.Timeout | undefined;
  const save = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      if (window.isDestroyed()) return;
      const state: WindowState = {
        bounds: window.getNormalBounds(),
        maximized: window.isMaximized(),
      };
      writeWindowState(state).catch((cause: unknown) => {
        console.warn("could not save window state", cause);
      });
    }, SAVE_DEBOUNCE_MS);
  };
  window.on("resize", save);
  window.on("move", save);
  window.on("maximize", save);
  window.on("unmaximize", save);
}
