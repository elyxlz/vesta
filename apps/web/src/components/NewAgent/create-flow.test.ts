import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { AgentStatusError, type ProviderResult } from "@/api/agents";
import {
  applyProviderSetup,
  classifyCreateFailure,
  isCredentialRejection,
  prepareAgentShell,
  type ProviderFlowDeps,
  type ShellFlowDeps,
} from "./create-flow";

describe("classifyCreateFailure", () => {
  it.each<{
    name: string;
    error: () => unknown;
    firstAttempt: boolean;
    expected: string;
  }>([
    {
      name: "a 409 on the first attempt is a name rejection",
      error: () => new ApiError(409, "agent 'luna' already exists"),
      firstAttempt: true,
      expected: "name-rejected",
    },
    {
      name: "a 409 on a retry is phase 1 already done",
      error: () => new ApiError(409, "agent 'luna' already exists"),
      firstAttempt: false,
      expected: "already-created",
    },
    {
      name: "a 400 is a name rejection on the first attempt",
      error: () => new ApiError(400, "agent name must be 1-32 characters"),
      firstAttempt: true,
      expected: "name-rejected",
    },
    {
      name: "a 400 is a name rejection on a retry",
      error: () => new ApiError(400, "agent name must be 1-32 characters"),
      firstAttempt: false,
      expected: "name-rejected",
    },
    {
      name: "a server error is retryable in place",
      error: () => new ApiError(500, "docker error"),
      firstAttempt: false,
      expected: "retryable",
    },
    {
      name: "a network failure is retryable in place",
      error: () => new TypeError("failed to fetch"),
      firstAttempt: true,
      expected: "retryable",
    },
  ])("$name", ({ error, firstAttempt, expected }) => {
    expect(classifyCreateFailure(error(), firstAttempt)).toBe(expected);
  });
});

describe("isCredentialRejection", () => {
  it("rejects the credential only on a 4xx from provisioning", () => {
    expect(
      isCredentialRejection(new ApiError(400, "invalid credentials")),
    ).toBe(true);
    expect(isCredentialRejection(new ApiError(422, "bad provider body"))).toBe(
      true,
    );
    expect(isCredentialRejection(new ApiError(500, "agent unreachable"))).toBe(
      false,
    );
    expect(isCredentialRejection(new TypeError("failed to fetch"))).toBe(false);
  });
});

function shellDeps(overrides: Partial<ShellFlowDeps> = {}): ShellFlowDeps {
  return {
    createAgent: vi.fn((_name: string) => Promise.resolve()),
    waitUntilRunning: vi.fn((_name: string, _timeout: number) =>
      Promise.resolve(),
    ),
    waitUntilReady: vi.fn((_name: string, _timeout: number) =>
      Promise.resolve(),
    ),
    ...overrides,
  };
}

describe("prepareAgentShell", () => {
  it("moves a fresh unprovisioned shell to provider setup", async () => {
    const deps = shellDeps({
      waitUntilReady: vi.fn(() =>
        Promise.reject(new AgentStatusError("luna", "unprovisioned")),
      ),
    });

    await expect(
      prepareAgentShell("luna", true, 10_000, deps),
    ).resolves.toEqual({ kind: "needs-provider" });
    expect(deps.createAgent).toHaveBeenCalledWith("luna");
    expect(deps.waitUntilRunning).toHaveBeenCalledWith("luna", 10_000);
  });

  it("resumes an existing shell and finishes when it is already ready", async () => {
    const deps = shellDeps({
      createAgent: vi.fn(() =>
        Promise.reject(new ApiError(409, "already exists")),
      ),
    });

    await expect(
      prepareAgentShell("luna", false, 10_000, deps),
    ).resolves.toEqual({ kind: "ready" });
    expect(deps.waitUntilReady).toHaveBeenCalledWith("luna", 10_000);
  });

  it("does not adopt an unrelated agent on the first create attempt", async () => {
    const conflict = new ApiError(409, "already exists");
    const deps = shellDeps({
      createAgent: vi.fn(() => Promise.reject(conflict)),
    });

    await expect(
      prepareAgentShell("luna", true, 10_000, deps),
    ).resolves.toEqual({ kind: "name-rejected", error: conflict });
    expect(deps.waitUntilRunning).not.toHaveBeenCalled();
  });
});

function providerDeps(
  overrides: Partial<ProviderFlowDeps> = {},
): ProviderFlowDeps {
  return {
    setProvider: vi.fn(
      (
        _name: string,
        _provider: ProviderResult,
        _personality?: string,
        _timezone?: string,
      ) => Promise.resolve(),
    ),
    waitUntilReady: vi.fn((_name: string, _timeout: number) =>
      Promise.resolve(),
    ),
    ...overrides,
  };
}

const CLAUDE: ProviderResult = {
  kind: "claude",
  credentials: "{}",
  model: "opus-latest",
};

describe("applyProviderSetup", () => {
  it("waits for boot completion after installing the provider", async () => {
    const deps = providerDeps();

    await expect(
      applyProviderSetup(
        {
          name: "luna",
          provider: CLAUDE,
          personality: "dry",
          timezone: "Europe/London",
          timeoutMs: 10_000,
        },
        deps,
      ),
    ).resolves.toEqual({ kind: "ready" });
    expect(deps.setProvider).toHaveBeenCalledWith(
      "luna",
      CLAUDE,
      "dry",
      "Europe/London",
    );
    expect(deps.waitUntilReady).toHaveBeenCalledWith("luna", 10_000);
  });

  it("returns credential failures to the provider step without polling", async () => {
    const rejected = new ApiError(400, "invalid credentials");
    const deps = providerDeps({
      setProvider: vi.fn(() => Promise.reject(rejected)),
    });

    await expect(
      applyProviderSetup(
        {
          name: "luna",
          provider: CLAUDE,
          personality: "dry",
          timezone: "Europe/London",
          timeoutMs: 10_000,
        },
        deps,
      ),
    ).resolves.toEqual({ kind: "credential-rejected", error: rejected });
    expect(deps.waitUntilReady).not.toHaveBeenCalled();
  });

  it("returns to provider setup when readiness needs user action", async () => {
    const deps = providerDeps({
      waitUntilReady: vi.fn(() =>
        Promise.reject(new AgentStatusError("luna", "not_authenticated")),
      ),
    });

    await expect(
      applyProviderSetup(
        {
          name: "luna",
          provider: CLAUDE,
          personality: "dry",
          timezone: "Europe/London",
          timeoutMs: 10_000,
        },
        deps,
      ),
    ).resolves.toEqual({ kind: "needs-provider" });
  });
});
