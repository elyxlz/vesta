import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { classifyCreateFailure, isCredentialRejection } from "./create-flow";

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
