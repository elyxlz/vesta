import type { Registry } from "./registry.d.mts";
export interface CaptureSelection {
  suite: "pages" | "states" | "all";
  page: string;
}
export function captureSelection(
  env?: Record<string, string | undefined>,
): CaptureSelection;
export function selectRegistry(
  registry: Registry,
  selection?: CaptureSelection,
): Registry;
