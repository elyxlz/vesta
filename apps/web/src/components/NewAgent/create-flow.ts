import { ApiError } from "@/api/client";

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
