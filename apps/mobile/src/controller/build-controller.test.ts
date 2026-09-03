import { describe, expect, it, vi } from "vitest";
import { createSession, type ControllerDeps } from "@vesta/core";
import { buildController } from "./build-controller";

const captured = vi.hoisted(() => ({ deps: null as ControllerDeps | null }));

vi.mock("@vesta/core", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@vesta/core")>()),
  createController: (deps: ControllerDeps) => {
    captured.deps = deps;
    return { close: vi.fn() };
  },
}));

function fakeSession() {
  return createSession({
    fetch: () => Promise.reject(new Error("unused")),
    read: () => ({
      url: "https://gateway.test",
      accessToken: "tok en",
      refreshToken: "refresh",
      expiresAt: Number.MAX_SAFE_INTEGER,
      hosted: false,
    }),
    write: () => undefined,
  });
}

function deps(): ControllerDeps {
  const value = captured.deps;
  if (!value) throw new Error("createController was not called");
  return value;
}

// The session owns token stamping, the refresh pre-flight, and the http client (core's session
// tests); here it is only what buildController hands the controller that matters.
describe("buildController", () => {
  it("hands the controller the app's one session as a mobile client", () => {
    const session = fakeSession();
    buildController(session, "0.1.179", {
      id: "dev-1",
      descriptor: "Vesta on iPhone",
    });

    expect(deps().session).toBe(session);
    expect(deps().sync.clientKind).toBe("mobile");
    expect(deps().sync.clientVersion).toBe("0.1.179");
    expect(deps().sync.device).toEqual({
      id: "dev-1",
      descriptor: "Vesta on iPhone",
    });
  });

  it("lets a development build and an unidentified device stay unreported", () => {
    buildController(fakeSession());

    expect(deps().sync.clientVersion).toBeUndefined();
    expect(deps().sync.device).toBeUndefined();
  });
});
