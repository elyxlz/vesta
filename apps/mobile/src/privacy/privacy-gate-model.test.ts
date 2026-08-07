import { describe, expect, it } from "vitest";
import {
  privacyGateNavigationAction,
  shouldAutomaticallyUnlock,
  type PrivacyGateNavigationAction,
} from "./privacy-gate-model";

interface Case {
  name: string;
  blocked: boolean;
  presentationReady: boolean;
  privacyRouteActive: boolean;
  replaceActiveRoute: boolean;
  sessionStatus: "booting" | "disconnected" | "connected";
  canGoBack: boolean;
  action: PrivacyGateNavigationAction;
}

const cases: Case[] = [
  {
    name: "pushes privacy over ordinary content",
    blocked: true,
    presentationReady: true,
    privacyRouteActive: false,
    replaceActiveRoute: false,
    sessionStatus: "connected",
    canGoBack: true,
    action: "push-privacy",
  },
  {
    name: "replaces another native sheet with privacy",
    blocked: true,
    presentationReady: true,
    privacyRouteActive: false,
    replaceActiveRoute: true,
    sessionStatus: "connected",
    canGoBack: true,
    action: "replace-privacy",
  },
  {
    name: "leaves the active privacy sheet alone while blocked",
    blocked: true,
    presentationReady: true,
    privacyRouteActive: true,
    replaceActiveRoute: false,
    sessionStatus: "connected",
    canGoBack: true,
    action: "none",
  },
  {
    name: "returns to connected history after unlock",
    blocked: false,
    presentationReady: true,
    privacyRouteActive: true,
    replaceActiveRoute: false,
    sessionStatus: "connected",
    canGoBack: true,
    action: "back",
  },
  {
    name: "recovers a root-only connected privacy route",
    blocked: false,
    presentationReady: true,
    privacyRouteActive: true,
    replaceActiveRoute: false,
    sessionStatus: "connected",
    canGoBack: false,
    action: "replace-root",
  },
  {
    name: "recovers to connect when the gateway was disconnected",
    blocked: false,
    presentationReady: true,
    privacyRouteActive: true,
    replaceActiveRoute: false,
    sessionStatus: "disconnected",
    canGoBack: false,
    action: "dismiss-to-connect",
  },
  {
    name: "waits for session restoration before dismissing privacy",
    blocked: false,
    presentationReady: true,
    privacyRouteActive: true,
    replaceActiveRoute: false,
    sessionStatus: "booting",
    canGoBack: false,
    action: "none",
  },
  {
    name: "waits to present privacy until startup state is stable",
    blocked: true,
    presentationReady: false,
    privacyRouteActive: false,
    replaceActiveRoute: false,
    sessionStatus: "booting",
    canGoBack: false,
    action: "none",
  },
];

describe("privacyGateNavigationAction", () => {
  it.each(cases)("$name", ({ action, ...input }) => {
    expect(privacyGateNavigationAction(input)).toBe(action);
  });
});

describe("shouldAutomaticallyUnlock", () => {
  const ready = {
    presentationReady: true,
    privacyRouteActive: true,
    hydrated: true,
    locked: true,
    authenticating: false,
    initializationFailed: false,
    attempted: false,
  };

  it("starts authentication only after the privacy route is active", () => {
    expect(shouldAutomaticallyUnlock(ready)).toBe(true);
    expect(
      shouldAutomaticallyUnlock({ ...ready, privacyRouteActive: false }),
    ).toBe(false);
  });

  it("does not automatically retry a completed authentication attempt", () => {
    expect(shouldAutomaticallyUnlock({ ...ready, attempted: true })).toBe(
      false,
    );
    expect(shouldAutomaticallyUnlock({ ...ready, authenticating: true })).toBe(
      false,
    );
  });
});
