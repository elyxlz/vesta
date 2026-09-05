import { describe, expect, it } from "vitest";
import {
  notificationNavigationDecision,
  pendingNotificationFromData,
  pushOpensAgentPage,
  readPendingNotification,
} from "./notification-routing";

const pending = {
  identifier: "notification-1",
  agent: "alex",
  eventType: "chat",
  gateway: "https://first.vesta.run",
  room: "dm:alex",
};

describe("notification navigation", () => {
  it("validates and restores a pending notification intent", () => {
    expect(
      pendingNotificationFromData(
        {
          agent: " alex ",
          eventType: "chat",
          gateway: "https://first.vesta.run",
          route: "/agent/alex/chat",
        },
        "notification-1",
      ),
    ).toEqual(pending);
    expect(readPendingNotification(JSON.stringify(pending))).toEqual(pending);
    expect(pendingNotificationFromData({}, "bad")).toBeNull();
  });

  // The gateway stamps the route; the room it names is what decides the screen, so a reply in a
  // group opens that room while every agent-shaped route stays on the agent page.
  it.each([
    { name: "a direct chat push", route: "/agent/alex/chat", room: "dm:alex" },
    { name: "an agent news push", route: "/agent/alex", room: "dm:alex" },
    { name: "a group push", route: "/chat/grp-trip", room: "grp-trip" },
    { name: "an escaped room id", route: "/chat/grp%3Atrip", room: "grp:trip" },
    { name: "a gateway-wide push", route: "/", room: "dm:alex" },
    { name: "a push with no route at all", route: undefined, room: "dm:alex" },
  ])("reads $name as $room", ({ route, room }) => {
    expect(
      pendingNotificationFromData({ agent: "alex", route }, "n")?.room,
    ).toBe(room);
  });

  it("opens the agent page for a direct room and the room screen otherwise", () => {
    expect(pushOpensAgentPage(pending)).toBe(true);
    expect(pushOpensAgentPage({ ...pending, room: "grp-trip" })).toBe(false);
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
