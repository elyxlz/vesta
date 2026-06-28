import { describe, it, expect, vi, beforeEach } from "vitest";
import * as client from "./client";
import {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
} from "./agents";

describe("notification rules api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("getNotificationInterruptRules unwraps the rules array", async () => {
    const spy = vi.spyOn(client, "apiJson").mockResolvedValue({
      rules: [{ id: "a", source: "twitter", action: "pool" }],
    });
    const rules = await getNotificationInterruptRules("bob");
    expect(spy).toHaveBeenCalledWith(
      "/agents/bob/config/notification-interrupt-rules",
    );
    expect(rules).toEqual([{ id: "a", source: "twitter", action: "pool" }]);
  });

  it("setNotificationInterruptRules PUTs the full list and returns saved rules", async () => {
    const spy = vi.spyOn(client, "apiJson").mockResolvedValue({
      rules: [{ id: "x", source: "twitter", action: "pool" }],
    });
    const out = await setNotificationInterruptRules("bob", [
      { id: "", source: "twitter", action: "pool" },
    ]);
    expect(spy).toHaveBeenCalledWith(
      "/agents/bob/config/notification-interrupt-rules",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          rules: [{ id: "", source: "twitter", action: "pool" }],
        }),
      }),
    );
    expect(out).toEqual([{ id: "x", source: "twitter", action: "pool" }]);
  });
});
