import { afterEach, describe, expect, it } from "vitest";
import {
  resetForegroundNotificationPolicyForTests,
  setSyncConnected,
  setVisibleAgentSocket,
  shouldPresentForegroundNotification,
} from "./foreground-policy";

afterEach(resetForegroundNotificationPolicyForTests);

describe("foreground notification presentation", () => {
  it("suppresses the push for any agent while sync is connected", () => {
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

  it("hides a duplicate only for the visible agent with a healthy socket", () => {
    setVisibleAgentSocket("https://first.vesta.run", "alex", true);
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        gateway: "https://first.vesta.run",
      }),
    ).toBe(false);
    expect(shouldPresentForegroundNotification({ agent: "other" })).toBe(true);
  });

  it("shows the notification while the visible agent socket reconnects", () => {
    setVisibleAgentSocket("https://first.vesta.run", "alex", false);
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(true);
  });

  it("shows a stale notification from a different gateway", () => {
    setVisibleAgentSocket("https://second.vesta.run", "alex", true);
    expect(
      shouldPresentForegroundNotification({
        agent: "alex",
        gateway: "https://first.vesta.run",
      }),
    ).toBe(true);
  });

  it("clears visibility when the agent page unmounts", () => {
    const clear = setVisibleAgentSocket(
      "https://first.vesta.run",
      "alex",
      true,
    );
    clear();
    expect(shouldPresentForegroundNotification({ agent: "alex" })).toBe(true);
  });
});
