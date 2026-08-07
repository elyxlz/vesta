import { describe, expect, it, vi } from "vitest";
import { RESTART_REASONS, restartBody } from "@vesta/core";
import type { ApiClient } from "./client";
import { restartAgent, setAgentBackupSettings } from "./endpoints";

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
  it("sends no body for a plain manual restart, leaving vestad to name it", async () => {
    const { api, request } = apiStub();

    await restartAgent(api, "luna");

    expect(request).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
    });
  });

  it("forwards a specific lifecycle reason", async () => {
    const { api, request } = apiStub();

    await restartAgent(api, "luna", RESTART_REASONS.context);

    expect(request).toHaveBeenCalledWith("/agents/luna/restart", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(restartBody(RESTART_REASONS.context)),
    });
  });
});

describe("setAgentBackupSettings", () => {
  it("PUTs the enabled flag to the per-agent backup settings path", async () => {
    const json = vi.fn().mockResolvedValue({
      enabled: false,
      retention: { periodic: 2, pre_update_versions: 2 },
      has_override: true,
    });
    const api = {
      json,
      jsonInit: (method: string, body: unknown) => ({
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    } as unknown as ApiClient;

    await setAgentBackupSettings(api, "luna", false);

    expect(json).toHaveBeenCalledWith("/agents/luna/settings/backup", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
    });
  });
});
