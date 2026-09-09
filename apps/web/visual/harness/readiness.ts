import type { Page } from "@playwright/test";

// Startup holds, debounces and delayed transitions can look stable before
// firing. Track short one-shot timers at the browser boundary; long refresh
// timers and intervals must not keep an otherwise settled screen waiting.
export async function installReadiness(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const pending = new Map<number, number>();
    const schedule = window.setTimeout.bind(window);
    const cancel = window.clearTimeout.bind(window);
    Object.defineProperty(window, "__visualPendingTimers", {
      get: () => pending.size,
    });
    window.setTimeout = new Proxy(schedule, {
      apply(target, receiver, args: unknown[]) {
        const id: unknown = Reflect.apply(target, receiver, args);
        const delay = Number(args[1] ?? 0);
        if (typeof id === "number" && delay > 0 && delay <= 2000) {
          pending.set(
            id,
            schedule(() => pending.delete(id), delay),
          );
        }
        return id;
      },
    });
    window.clearTimeout = new Proxy(cancel, {
      apply(target, receiver, args: unknown[]) {
        const id = args[0];
        if (typeof id === "number") {
          cancel(pending.get(id));
          pending.delete(id);
        }
        Reflect.apply(target, receiver, args);
      },
    });
  });
}

export async function waitForReadiness(page: Page): Promise<void> {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  await page.waitForFunction(
    () => Reflect.get(window, "__visualPendingTimers") === 0,
    undefined,
    { timeout: 8000 },
  );
}
