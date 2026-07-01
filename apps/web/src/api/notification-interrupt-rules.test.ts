import { describe, it, expect, vi, beforeEach } from "vitest";
import * as client from "./client";
import {
  getNotificationInterruptRules,
  setNotificationInterruptRules,
} from "./agents";

describe("notification rules api", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("getNotificationInterruptRules reads notification_rules from config", async () => {
    const spy = vi.spyOn(client, "apiJson").mockResolvedValue({
      notification_rules: [{ id: "a", source: "twitter", action: "pool" }],
    });
    const rules = await getNotificationInterruptRules("bob");
    expect(spy).toHaveBeenCalledWith("/agents/bob/config");
    expect(rules).toEqual([{ id: "a", source: "twitter", action: "pool" }]);
  });

  it("getNotificationInterruptRules defaults to [] when absent", async () => {
    vi.spyOn(client, "apiJson").mockResolvedValue({});
    const rules = await getNotificationInterruptRules("bob");
    expect(rules).toEqual([]);
  });

  it("setNotificationInterruptRules PUTs notification_rules and returns them", async () => {
    const spy = vi
      .spyOn(client, "apiFetch")
      .mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    const rules = [{ id: "x", source: "twitter", action: "pool" as const }];
    const out = await setNotificationInterruptRules("bob", rules);
    expect(spy).toHaveBeenCalledWith(
      "/agents/bob/config",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ notification_rules: rules }),
      }),
    );
    expect(out).toEqual(rules);
  });
});
