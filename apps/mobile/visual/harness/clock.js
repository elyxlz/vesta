"use strict";

// Freeze wall time only. Native timers and performance.now still advance,
// so layout, gestures, and async work keep their real lifecycle.
const instant = Date.parse("2026-08-01T09:41:00.000Z");
const RealDate = globalThis.Date;
globalThis.Date = new Proxy(RealDate, {
  apply() {
    return new RealDate(instant).toString();
  },
  construct(target, args, newTarget) {
    return Reflect.construct(target, args.length ? args : [instant], newTarget);
  },
  get(target, property, receiver) {
    return property === "now"
      ? () => instant
      : Reflect.get(target, property, receiver);
  },
});
