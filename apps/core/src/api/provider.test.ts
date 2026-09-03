import { describe, expect, it, vi } from "vitest";
import type { HttpClient } from "../transport/http";
import { setAgentBackupSettings } from "./backups";
import {
  completeClaudeOAuth,
  completeOpenAIOAuth,
  fetchAgentClaudeModels,
  fetchOpenRouterModels,
  getProvider,
  startClaudeOAuth,
  startOpenAIOAuth,
  validateOpenRouterKey,
} from "./provider";

const JSON_HEADERS = { "Content-Type": "application/json" };

function http() {
  const json = vi.fn<(path: string, init?: RequestInit) => Promise<unknown>>();
  const request = vi
    .fn<HttpClient["request"]>()
    .mockResolvedValue(new Response());
  const client: HttpClient = { json: json as HttpClient["json"], request };
  return { client, json, request };
}

describe("setAgentBackupSettings", () => {
  it("PUTs the enabled flag to the per-agent backup settings path", async () => {
    const { client, json } = http();
    json.mockResolvedValue({
      enabled: false,
      retention: { periodic: 2, pre_update_versions: 2 },
      has_override: true,
    });

    await setAgentBackupSettings(client, "luna", false);

    expect(json).toHaveBeenCalledWith("/agents/luna/settings/backup", {
      method: "PUT",
      headers: JSON_HEADERS,
      body: JSON.stringify({ enabled: false }),
    });
  });
});

describe("fetchAgentClaudeModels", () => {
  it("GETs the agent's live Claude catalog", async () => {
    const { client, json } = http();
    json.mockResolvedValue([
      { slug: "claude-opus-5", label: "Claude Opus 5", author: "Anthropic" },
    ]);

    const models = await fetchAgentClaudeModels(client, "luna");

    expect(json).toHaveBeenCalledWith("/agents/luna/provider/models");
    expect(models[0]?.slug).toBe("claude-opus-5");
  });
});

describe("agent-owned provider resources", () => {
  it("reads current provider state and its catalog in one request", async () => {
    const { client, json } = http();
    const catalog = { default_provider: "claude" as const, providers: {} };
    json.mockResolvedValue({ authed: false, catalog });

    await expect(getProvider(client, "luna one")).resolves.toEqual({
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
    const { client, json, request } = http();
    json
      .mockResolvedValueOnce({
        auth_url: "claude",
        session_id: "claude-session",
      })
      .mockResolvedValueOnce({
        auth_url: "openai",
        user_code: "CODE",
        session_id: "openai-session",
      })
      .mockResolvedValueOnce({ credentials: "claude-credentials" })
      .mockResolvedValueOnce({ credentials: "openai-credentials" })
      .mockResolvedValueOnce([]);

    await startClaudeOAuth(client, "luna one");
    await startOpenAIOAuth(client, "luna one");
    await completeClaudeOAuth(client, "luna one", "claude-session", "code");
    await completeOpenAIOAuth(client, "luna one", "openai-session");
    await fetchOpenRouterModels(client, "luna one");
    await validateOpenRouterKey(client, "luna one", "sk-test");

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
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ session_id: "claude-session", code: "code" }),
      },
    );
    expect(json).toHaveBeenNthCalledWith(
      4,
      "/agents/luna%20one/providers/openai/oauth/complete",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ session_id: "openai-session" }),
      },
    );
    expect(json).toHaveBeenNthCalledWith(
      5,
      "/agents/luna%20one/providers/openrouter/models/top",
    );
    expect(request).toHaveBeenCalledWith(
      "/agents/luna%20one/providers/openrouter/validate-key",
      {
        method: "POST",
        headers: JSON_HEADERS,
        body: JSON.stringify({ key: "sk-test" }),
      },
    );
  });
});
