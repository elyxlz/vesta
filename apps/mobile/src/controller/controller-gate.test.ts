import { describe, expect, it } from "vitest";
import { controllerGateAction, type GateAction, type GateInput } from "./controller-gate";

const off: GateInput = { connected: false, foreground: false };
const bg: GateInput = { connected: true, foreground: false };
const live: GateInput = { connected: true, foreground: true };
const orphan: GateInput = { connected: false, foreground: true };

const cases: { name: string; prev: GateInput; next: GateInput; action: GateAction }[] = [
  { name: "connected+foreground from nothing builds", prev: off, next: live, action: "build" },
  { name: "connecting while already foreground builds", prev: orphan, next: live, action: "build" },
  { name: "going background closes", prev: live, next: bg, action: "close" },
  { name: "returning to foreground builds", prev: bg, next: live, action: "build" },
  { name: "disconnect while foreground closes", prev: live, next: orphan, action: "close" },
  { name: "staying live is idle", prev: live, next: live, action: "idle" },
  { name: "staying background is idle", prev: bg, next: bg, action: "idle" },
  { name: "background then disconnect is idle", prev: bg, next: off, action: "idle" },
  { name: "foreground while disconnected is idle", prev: off, next: orphan, action: "idle" },
];

describe("controllerGateAction", () => {
  it.each(cases)("$name", ({ prev, next, action }) => {
    expect(controllerGateAction(prev, next)).toBe(action);
  });
});
