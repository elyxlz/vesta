import { describe, expect, it } from "vitest";
import { ApiError } from "@/api/client";
import { classifyCreateFailure, isCredentialRejection } from "./create-flow";

describe("classifyCreateFailure", () => {
  it("treats a 409 on the first attempt as a name rejection", () => {
    const conflict = new ApiError(409, "agent 'luna' already exists");
    expect(classifyCreateFailure(conflict, true)).toBe("name-rejected");
  });

  it("treats a 409 on a retry as phase 1 already done", () => {
    const conflict = new ApiError(409, "agent 'luna' already exists");
    expect(classifyCreateFailure(conflict, false)).toBe("already-created");
  });

  it("treats a 400 as a name rejection on any attempt", () => {
    const invalid = new ApiError(400, "agent name must be 1-32 characters");
    expect(classifyCreateFailure(invalid, true)).toBe("name-rejected");
    expect(classifyCreateFailure(invalid, false)).toBe("name-rejected");
  });

  it("treats server errors and network failures as retryable in place", () => {
    expect(
      classifyCreateFailure(new ApiError(500, "docker error"), false),
    ).toBe("retryable");
    expect(classifyCreateFailure(new TypeError("failed to fetch"), true)).toBe(
      "retryable",
    );
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
