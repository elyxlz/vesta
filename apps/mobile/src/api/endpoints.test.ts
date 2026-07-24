import { describe, expect, it, vi } from "vitest";
import { RESTART_REASONS } from "@vesta/core";
import type { ApiClient } from "./client";
import { restartAgent } from "./endpoints";

function apiStub() {
  const request = vi.fn().mockResolvedValue(new Response());
  const api = {
    request,
    jsonInit: (method: string, body: unknown) => ({
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  } as unknown as ApiClient;
  return { api, request };
}

describe("restartAgent", () => {
  it("sends the canonical manual reason by default", async () => {
    const { api, request } = apiStub();

    await restartAgent(api, "luna");

    expect(request).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: RESTART_REASONS.manual.logReason,
        agent_message: RESTART_REASONS.manual.agentMessage,
      }),
    });
  });

  it("forwards a specific lifecycle reason", async () => {
    const { api, request } = apiStub();

    await restartAgent(api, "luna", RESTART_REASONS.context);

    expect(request).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: RESTART_REASONS.context.logReason,
        agent_message: RESTART_REASONS.context.agentMessage,
      }),
    });
  });
});
