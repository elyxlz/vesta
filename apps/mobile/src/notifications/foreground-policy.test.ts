import { afterEach, describe, expect, it } from "vitest";
import {
  activeRoomId,
  resetForegroundNotificationPolicyForTests,
  setSyncConnected,
  setVisibleRoomSocket,
  shouldPresentForegroundNotification,
} from "./foreground-policy";

afterEach(resetForegroundNotificationPolicyForTests);

describe("foreground notification presentation", () => {
  it("suppresses the push for any conversation while sync is connected", () => {
    setSyncConnected(true);
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(false);
    expect(shouldPresentForegroundNotification({ agent: "other" })).toBe(false);
    expect(shouldPresentForegroundNotification(null)).toBe(false);
  });

  it("presents the push as a fallback once sync goes down", () => {
    setSyncConnected(true);
    setSyncConnected(false);
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(true);
  });

  it("hides a duplicate only for the visible room with a healthy socket", () => {
    setVisibleRoomSocket("https://first.vesta.run", "dm:alex", true);
    expect(activeRoomId()).toBe("dm:alex");
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        gateway: "https://first.vesta.run",
        route: "/agent/alex/chat",
      }),
    ).toBe(false);
    expect(shouldPresentForegroundNotification({ agent: "other" })).toBe(true);
  });

  // A room push and a direct push name different conversations even when the same agent wrote both.
  it("shows a group reply while that agent's direct chat is open", () => {
    setVisibleRoomSocket("https://first.vesta.run", "dm:alex", true);
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        route: "/chat/grp-trip",
      }),
    ).toBe(true);
  });

  it("hides a group reply while that group is open", () => {
    setVisibleRoomSocket("https://first.vesta.run", "grp-trip", true);
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        route: "/chat/grp-trip",
      }),
    ).toBe(false);
  });

  it("shows the notification while the visible room socket reconnects", () => {
    setVisibleRoomSocket("https://first.vesta.run", "dm:alex", false);
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(true);
  });

  it("shows a stale notification from a different gateway", () => {
    setVisibleRoomSocket("https://second.vesta.run", "dm:alex", true);
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        gateway: "https://first.vesta.run",
      }),
    ).toBe(true);
  });

  it("clears visibility when the chat screen unmounts", () => {
    const clear = setVisibleRoomSocket(
      "https://first.vesta.run",
      "dm:alex",
      true,
    );
    clear();
    expect(activeRoomId()).toBeNull();
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(true);
  });
});
