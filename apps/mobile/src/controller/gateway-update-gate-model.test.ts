import { describe, expect, it } from "vitest";
import {
  gatewayUpdateGateNavigationAction,
  type GatewayUpdateGateNavigationAction,
} from "./gateway-update-gate-model";

interface Case {
  name: string;
  blocked: boolean;
  operationRunning: boolean;
  privacyBlocked: boolean;
  privacyRouteActive: boolean;
  gatewayUpdateRouteActive: boolean;
  replaceActiveRoute: boolean;
  action: GatewayUpdateGateNavigationAction;
}

const cases: Case[] = [
  {
    name: "waits while privacy is blocked",
    blocked: true,
    operationRunning: false,
    privacyBlocked: true,
    privacyRouteActive: true,
    gatewayUpdateRouteActive: false,
    replaceActiveRoute: false,
    action: "none",
  },
  {
    name: "waits for an unlocked privacy sheet to finish dismissing",
    blocked: true,
    operationRunning: false,
    privacyBlocked: false,
    privacyRouteActive: true,
    gatewayUpdateRouteActive: false,
    replaceActiveRoute: false,
    action: "none",
  },
  {
    name: "pushes the update after the privacy sheet is gone",
    blocked: true,
    operationRunning: false,
    privacyBlocked: false,
    privacyRouteActive: false,
    gatewayUpdateRouteActive: false,
    replaceActiveRoute: false,
    action: "push-update",
  },
  {
    name: "replaces another native sheet with the update",
    blocked: true,
    operationRunning: false,
    privacyBlocked: false,
    privacyRouteActive: false,
    gatewayUpdateRouteActive: false,
    replaceActiveRoute: true,
    action: "replace-update",
  },
  {
    name: "dismisses the update after compatibility recovers",
    blocked: false,
    operationRunning: false,
    privacyBlocked: false,
    privacyRouteActive: false,
    gatewayUpdateRouteActive: true,
    replaceActiveRoute: false,
    action: "dismiss",
  },
  {
    name: "hands the presented sheet off home once the update operation starts",
    blocked: true,
    operationRunning: true,
    privacyBlocked: false,
    privacyRouteActive: false,
    gatewayUpdateRouteActive: true,
    replaceActiveRoute: false,
    action: "dismiss-home",
  },
  {
    name: "never re-presents the sheet while the operation runs",
    blocked: true,
    operationRunning: true,
    privacyBlocked: false,
    privacyRouteActive: false,
    gatewayUpdateRouteActive: false,
    replaceActiveRoute: false,
    action: "none",
  },
];

describe("gatewayUpdateGateNavigationAction", () => {
  it.each(cases)("$name", ({ action, ...input }) => {
    expect(gatewayUpdateGateNavigationAction(input)).toBe(action);
  });
});
