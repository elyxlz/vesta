import { agentNeedsUser } from "@vesta/core";
import { ApiError } from "@/api/client";
import {
  AgentStatusError,
  createAgent,
  setProvider,
  waitUntilReady,
  waitUntilRunning,
  type ProviderResult,
} from "@/api/agents";

/// Disposition of a failed create (POST /agents) during the wizard.
/// "already-created": a 409 on a retry, the container from the failed attempt
/// exists, so phase 1 is already done and the pipeline proceeds.
/// "name-rejected": the name itself was refused (invalid, or taken by an agent
/// that predates this wizard run), only a different name can fix it.
/// "retryable": anything else (timeout, network, 5xx), retry in place.
export type CreateFailure = "already-created" | "name-rejected" | "retryable";

export function classifyCreateFailure(
  e: unknown,
  firstAttempt: boolean,
): CreateFailure {
  if (!(e instanceof ApiError)) return "retryable";
  if (e.status === 409)
    return firstAttempt ? "name-rejected" : "already-created";
  if (e.status === 400) return "name-rejected";
  return "retryable";
}

/// A 4xx from provisioning (PUT /provider) means the credential or config was
/// rejected: retrying the same payload cannot succeed, redo the provider step.
export function isCredentialRejection(e: unknown): boolean {
  return e instanceof ApiError && e.status >= 400 && e.status < 500;
}

export interface ShellFlowDeps {
  createAgent: typeof createAgent;
  waitUntilRunning: typeof waitUntilRunning;
  waitUntilReady: typeof waitUntilReady;
}

const SHELL_FLOW_DEPS: ShellFlowDeps = {
  createAgent,
  waitUntilRunning,
  waitUntilReady,
};

export type ShellFlowResult =
  | { kind: "ready" }
  | { kind: "needs-provider" }
  | { kind: "name-rejected"; error: unknown };

export async function prepareAgentShell(
  name: string,
  firstAttempt: boolean,
  timeoutMs: number,
  deps: ShellFlowDeps = SHELL_FLOW_DEPS,
): Promise<ShellFlowResult> {
  try {
    await deps.createAgent(name);
  } catch (caught: unknown) {
    const failure = classifyCreateFailure(caught, firstAttempt);
    if (failure === "name-rejected") {
      return { kind: "name-rejected", error: caught };
    }
    if (failure === "retryable") throw caught;
  }

  await deps.waitUntilRunning(name, timeoutMs);
  try {
    await deps.waitUntilReady(name, timeoutMs);
    return { kind: "ready" };
  } catch (caught: unknown) {
    if (caught instanceof AgentStatusError && agentNeedsUser(caught.status)) {
      return { kind: "needs-provider" };
    }
    throw caught;
  }
}

export interface ProviderFlowDeps {
  setProvider: typeof setProvider;
  waitUntilReady: typeof waitUntilReady;
}

const PROVIDER_FLOW_DEPS: ProviderFlowDeps = {
  setProvider,
  waitUntilReady,
};

export type ProviderFlowResult =
  | { kind: "ready" }
  | { kind: "needs-provider" }
  | { kind: "credential-rejected"; error: unknown };

export interface ProviderSetupInput {
  name: string;
  provider: ProviderResult;
  personality: string;
  timezone: string;
  timeoutMs: number;
}

export async function applyProviderSetup(
  input: ProviderSetupInput,
  deps: ProviderFlowDeps = PROVIDER_FLOW_DEPS,
): Promise<ProviderFlowResult> {
  try {
    await deps.setProvider(
      input.name,
      input.provider,
      input.personality,
      input.timezone,
    );
  } catch (caught: unknown) {
    if (isCredentialRejection(caught)) {
      return { kind: "credential-rejected", error: caught };
    }
    throw caught;
  }

  try {
    await deps.waitUntilReady(input.name, input.timeoutMs);
    return { kind: "ready" };
  } catch (caught: unknown) {
    if (caught instanceof AgentStatusError && agentNeedsUser(caught.status)) {
      return { kind: "needs-provider" };
    }
    throw caught;
  }
}
