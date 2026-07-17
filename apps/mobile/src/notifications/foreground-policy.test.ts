import { afterEach, describe, expect, it } from "vitest";
import {
  resetForegroundNotificationPolicyForTests,
  setVisibleAgentSocket,
  shouldPresentForegroundNotification,
} from "./foreground-policy";

afterEach(resetForegroundNotificationPolicyForTests);

describe("foreground notification presentation", () => {
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
