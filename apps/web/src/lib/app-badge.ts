type BadgeNavigator = Navigator & {
  setAppBadge?: (count?: number) => Promise<void>;
  clearAppBadge?: () => Promise<void>;
};

export function setAppBadge(on: boolean): void {
  if (typeof navigator === "undefined") return;
  const nav = navigator as BadgeNavigator;
  if (on) {
    nav.setAppBadge?.(1).catch(() => {});
  } else {
    nav.clearAppBadge?.().catch(() => {});
  }
}
