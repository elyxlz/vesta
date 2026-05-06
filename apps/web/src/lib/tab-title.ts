const DEFAULT_BASE = "Vesta";

export function setTabBaseTitle(base: string): void {
  if (typeof document === "undefined") return;
  document.title = base || DEFAULT_BASE;
}

export function resetTabBaseTitle(): void {
  if (typeof document === "undefined") return;
  document.title = DEFAULT_BASE;
}
