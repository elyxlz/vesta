import { beforeEach, describe, expect, it, vi } from "vitest";
import { RESTART_REASONS } from "@vesta/core";

const client = vi.hoisted(() => ({
  apiJson: vi.fn().mockResolvedValue({}),
}));

vi.mock("./client", () => ({
  apiFetch: vi.fn(),
  apiJson: client.apiJson,
  jsonInit: (method: string, body: unknown) => ({
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }),
}));

import { restartAgent } from "./agents";

describe("restartAgent", () => {
  beforeEach(() => {
    client.apiJson.mockClear();
  });

  it("sends the canonical manual reason by default", async () => {
    await restartAgent("luna");

    expect(client.apiJson).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: RESTART_REASONS.manual }),
    });
  });

  it("forwards a specific lifecycle reason", async () => {
    await restartAgent("luna", RESTART_REASONS.model);

    expect(client.apiJson).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: RESTART_REASONS.model }),
    });
  });
});
