import { beforeEach, describe, expect, it, vi } from "vitest";
import { RESTART_REASONS, restartBody } from "@vesta/core";

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

  it("sends no body for a plain manual restart, leaving vestad to name it", async () => {
    await restartAgent("luna");

    expect(client.apiJson).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
    });
  });

  it("forwards a specific lifecycle reason", async () => {
    await restartAgent("luna", RESTART_REASONS.model);

    expect(client.apiJson).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(restartBody(RESTART_REASONS.model)),
    });
  });
});
