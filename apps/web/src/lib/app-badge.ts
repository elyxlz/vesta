export function setAppBadge(on: boolean): void {
  if (typeof navigator === "undefined" || !("setAppBadge" in navigator)) return;
  if (on) {
    navigator.setAppBadge(1).catch(() => {
      /* badge is best-effort */
    });
  } else {
    navigator.clearAppBadge().catch(() => {
      /* badge is best-effort */
    });
  }
}
