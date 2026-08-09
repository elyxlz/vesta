import { describe, expect, it } from "vitest";
import {
  gatewayOperationRouteAction,
  type GatewayOperationRouteAction,
} from "./gateway-operation-route-model";

interface Case {
  name: string;
  operating: boolean;
  activeRoute: string | undefined;
  action: GatewayOperationRouteAction;
}

const cases: Case[] = [
  {
    name: "leaves navigation alone when nothing is running",
    operating: false,
    activeRoute: "agent",
    action: "none",
  },
  {
    name: "stays on home, which renders the operation",
    operating: true,
    activeRoute: undefined,
    action: "none",
  },
  {
    name: "keeps settings reachable while the operation runs",
    operating: true,
    activeRoute: "settings",
    action: "none",
  },
  {
    name: "sends an agent page home",
    operating: true,
    activeRoute: "agent",
    action: "home",
  },
  {
    name: "sends agent creation home",
    operating: true,
    activeRoute: "new-agent",
    action: "home",
  },
  {
    name: "leaves privacy to the privacy gate",
    operating: true,
    activeRoute: "privacy",
    action: "none",
  },
  {
    name: "leaves the gateway-update sheet to its own gate",
    operating: true,
    activeRoute: "gateway-update",
    action: "none",
  },
];

describe("gatewayOperationRouteAction", () => {
  it.each(cases)("$name", ({ operating, activeRoute, action }) => {
    expect(gatewayOperationRouteAction({ operating, activeRoute })).toBe(action);
  });
});
