import { describe, expect, it } from "vitest";
import type { SyncState } from "@vesta/core";
import {
  gatewayUpdateGateDecision,
  latchedGatewayBehind,
  type GatewayBehindLatch,
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
  backdropBlocked: boolean;
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
    backdropBlocked: false,
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
    backdropBlocked: false,
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
    backdropBlocked: true,
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
    backdropBlocked: true,
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
    backdropBlocked: false,
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
    backdropBlocked: false,
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
    backdropBlocked: false,
  },
];

describe("gatewayUpdateGateDecision", () => {
  it.each(cases)("$name", ({ action, backdropBlocked, ...input }) => {
    expect(gatewayUpdateGateDecision(input)).toEqual({
      action,
      backdropBlocked,
    });
  });
});

interface LatchCase {
  name: string;
  latch: GatewayBehindLatch;
  connectionKey: string | null;
  syncState: SyncState;
  behind: boolean;
}

const latchCases: LatchCase[] = [
  {
    name: "raises on a behind hello",
    latch: { key: "gw-a", behind: false },
    connectionKey: "gw-a",
    syncState: "gateway_behind",
    behind: true,
  },
  {
    name: "holds through the reconnect gap",
    latch: { key: "gw-a", behind: true },
    connectionKey: "gw-a",
    syncState: "reconnecting",
    behind: true,
  },
  {
    name: "clears on an accepted hello",
    latch: { key: "gw-a", behind: true },
    connectionKey: "gw-a",
    syncState: "open",
    behind: false,
  },
  {
    name: "starts unlatched on a gateway switch",
    latch: { key: "gw-a", behind: true },
    connectionKey: "gw-b",
    syncState: "reconnecting",
    behind: false,
  },
  {
    name: "stays down on a blip that was never behind",
    latch: { key: "gw-a", behind: false },
    connectionKey: "gw-a",
    syncState: "reconnecting",
    behind: false,
  },
];

describe("latchedGatewayBehind", () => {
  it.each(latchCases)("$name", ({ latch, connectionKey, syncState, behind }) => {
    expect(latchedGatewayBehind(latch, connectionKey, syncState)).toBe(behind);
  });
});
