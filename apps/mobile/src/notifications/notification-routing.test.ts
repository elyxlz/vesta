import { describe, expect, it } from "vitest";
import {
  notificationNavigationDecision,
  pendingNotificationFromData,
  readPendingNotification,
} from "./notification-routing";

const pending = {
  identifier: "notification-1",
  agent: "alex",
  eventType: "chat",
  gateway: "https://first.vesta.run",
};

describe("notification navigation", () => {
  it("validates and restores a pending notification intent", () => {
    expect(
      pendingNotificationFromData(
        {
          agent: " alex ",
          eventType: "chat",
          gateway: "https://first.vesta.run",
        },
        "notification-1",
      ),
    ).toEqual(pending);
    expect(readPendingNotification(JSON.stringify(pending))).toEqual(pending);
    expect(pendingNotificationFromData({}, "bad")).toBeNull();
  });

  it("waits until session navigation and the gateway agent list are ready", () => {
    expect(
      notificationNavigationDecision({
        pending,
        sessionStatus: "connected",
        reachable: true,
        agentsReady: true,
        agentNames: ["alex"],
        routeReady: false,
        currentGateway: "https://first.vesta.run",
      }),
    ).toBe("wait");
    expect(
      notificationNavigationDecision({
        pending,
        sessionStatus: "connected",
        reachable: false,
        agentsReady: true,
        agentNames: ["alex"],
        routeReady: true,
        currentGateway: "https://first.vesta.run",
      }),
    ).toBe("wait");
  });

  it("opens only an agent belonging to the connected gateway", () => {
    const ready = {
      pending,
      sessionStatus: "connected" as const,
      reachable: true,
      agentsReady: true,
      routeReady: true,
      currentGateway: "https://first.vesta.run",
    };
    expect(
      notificationNavigationDecision({ ...ready, agentNames: ["alex"] }),
    ).toBe("open");
    expect(
      notificationNavigationDecision({ ...ready, agentNames: ["other"] }),
    ).toBe("discard");
  });

  it("discards a stale notification after switching gateways", () => {
    expect(
      notificationNavigationDecision({
        pending,
        sessionStatus: "connected",
        reachable: true,
        agentsReady: true,
        agentNames: ["alex"],
        routeReady: true,
        currentGateway: "https://second.vesta.run",
      }),
    ).toBe("discard");
  });
});
