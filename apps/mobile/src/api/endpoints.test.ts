import { describe, expect, it, vi } from "vitest";
import { RESTART_REASONS, restartBody } from "@vesta/core";
import type { ApiClient } from "./client";
import {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  fetchClaudeModels,
  fetchOpenRouterModels,
  getProvider,
  renameAgent,
  restartAgent,
  setAgentBackupSettings,
  startClaudeOAuth,
  startOpenAIOAuth,
  validateOpenRouterKey,
} from "./endpoints";

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

describe("renameAgent", () => {
  it("PATCHes the encoded agent path and returns the canonical name", async () => {
    const json = vi.fn().mockResolvedValue({ name: "luna-prime" });
    const api = {
      json,
      jsonInit: (method: string, body: unknown) => ({
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    } as unknown as ApiClient;

    await expect(renameAgent(api, "luna one", "Luna Prime")).resolves.toBe(
      "luna-prime",
    );
    expect(json).toHaveBeenCalledWith("/agents/luna%20one", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: "Luna Prime" }),
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

describe("fetchClaudeModels", () => {
  it("GETs the agent's live Claude catalog", async () => {
    const json = vi
      .fn()
      .mockResolvedValue([
        { slug: "claude-opus-5", label: "Claude Opus 5", author: "Anthropic" },
      ]);
    const api = { json } as unknown as ApiClient;

    const models = await fetchClaudeModels(api, "luna");

    expect(json).toHaveBeenCalledWith("/agents/luna/provider/models");
    expect(models[0]?.slug).toBe("claude-opus-5");
  });
});

describe("agent-owned provider resources", () => {
  it("reads current provider state and its catalog in one request", async () => {
    const catalog = { default_provider: "claude" as const, providers: {} };
    const json = vi.fn().mockResolvedValue({ authed: false, catalog });
    const api = { json } as unknown as ApiClient;

    await expect(getProvider(api, "luna one")).resolves.toEqual({
      provider: {
        kind: "none",
        model: null,
        resolved_model: null,
        max_context_tokens: null,
        authed: false,
        plan: null,
      },
      catalog,
    });
    expect(json).toHaveBeenCalledOnce();
    expect(json).toHaveBeenCalledWith("/agents/luna%20one/provider");
  });

  it("keeps every setup operation inside the named agent relay", async () => {
    const json = vi
      .fn()
      .mockResolvedValueOnce({ auth_url: "claude", session_id: "claude-session" })
      .mockResolvedValueOnce({
        auth_url: "openai",
        user_code: "CODE",
        session_id: "openai-session",
      })
      .mockResolvedValueOnce({ credentials: "claude-credentials" })
      .mockResolvedValueOnce({ credentials: "openai-credentials" })
      .mockResolvedValueOnce([]);
    const request = vi.fn().mockResolvedValue(new Response());
    const api = {
      json,
      request,
      jsonInit: (method: string, body: unknown) => ({
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    } as unknown as ApiClient;

    await startClaudeOAuth(api, "luna one");
    await startOpenAIOAuth(api, "luna one");
    await completeClaudeOAuth(api, "luna one", "claude-session", "code");
    await completeOpenAIOAuth(api, "luna one", "openai-session");
    await fetchOpenRouterModels(api, "luna one");
    await validateOpenRouterKey(api, "luna one", "sk-test");

    expect(json).toHaveBeenNthCalledWith(
      1,
      "/agents/luna%20one/providers/claude/oauth/start",
      { method: "POST" },
    );
    expect(json).toHaveBeenNthCalledWith(
      2,
      "/agents/luna%20one/providers/openai/oauth/start",
      { method: "POST" },
    );
    expect(json).toHaveBeenNthCalledWith(
      3,
      "/agents/luna%20one/providers/claude/oauth/complete",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          session_id: "claude-session",
          code: "code",
        }),
      }),
    );
    expect(json).toHaveBeenNthCalledWith(
      4,
      "/agents/luna%20one/providers/openai/oauth/complete",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "openai-session" }),
      }),
    );
    expect(json).toHaveBeenNthCalledWith(
      5,
      "/agents/luna%20one/providers/openrouter/models/top",
    );
    expect(request).toHaveBeenCalledWith(
      "/agents/luna%20one/providers/openrouter/validate-key",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ key: "sk-test" }),
      }),
    );
  });
});
