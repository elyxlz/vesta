// Exercises sessionStorage and window.location, so it runs in the jsdom project.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OauthLoopback } from "./native/types";

const bridge = vi.hoisted(() => ({
  oauthLoopback: null as OauthLoopback | null,
  openExternal: vi.fn((_url: string) => Promise.resolve()),
}));
vi.mock("./native", () => ({ native: bridge }));
vi.mock("./connection", () => ({ setConnection: vi.fn() }));

import { setConnection } from "./connection";
import { completeHostedLogin, startNativeLogin } from "./pkce";

const VERIFIER_KEY = "vesta-pkce-verifier";
const STATE_KEY = "vesta-pkce-state";

const fetchMock =
  vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

function tokenResponse(body: object): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  sessionStorage.setItem(VERIFIER_KEY, "verifier-1");
  sessionStorage.setItem(STATE_KEY, "state-1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  sessionStorage.clear();
  bridge.oauthLoopback = null;
});

describe("completeHostedLogin", () => {
  it("rejects a returned state that does not match the one this page minted", async () => {
    await expect(completeHostedLogin("code", "someone-elses")).rejects.toThrow(
      "state mismatch",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("exchanges the code with the stored verifier and consumes it", async () => {
    fetchMock.mockResolvedValue(
      tokenResponse({ access_token: "tok", expires_in: 300 }),
    );
    await expect(completeHostedLogin("code", "state-1")).resolves.toEqual({
      accessToken: "tok",
      expiresIn: 300,
    });
    const body = fetchMock.mock.calls[0]?.[1]?.body;
    if (typeof body !== "string") throw new Error("expected a json body");
    expect(JSON.parse(body)).toEqual({
      code: "code",
      code_verifier: "verifier-1",
    });
    // Single use: a replayed callback finds no session.
    expect(sessionStorage.getItem(VERIFIER_KEY)).toBeNull();
    await expect(completeHostedLogin("code", "state-1")).rejects.toThrow(
      "login session expired",
    );
  });

  it("consumes the verifier even when the exchange fails", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 500 }));
    await expect(completeHostedLogin("code", "state-1")).rejects.toThrow(
      "could not complete sign-in",
    );
    expect(sessionStorage.getItem(VERIFIER_KEY)).toBeNull();
  });
});

describe("startNativeLogin", () => {
  // A loopback whose callback the test fires by hand.
  function fakeLoopback() {
    let callback: ((url: string) => void) | null = null;
    const cancel = vi.fn((_port: number) => Promise.resolve());
    const loopback: OauthLoopback = {
      start: () => Promise.resolve(4242),
      onCallback: (cb) => {
        callback = cb;
        return () => {
          callback = null;
        };
      },
      cancel,
    };
    const hit = (url: string) => callback?.(url);
    return { loopback, hit, cancel };
  }

  // The state the browser was sent with, read back from the authorize url.
  function sentState(): string {
    const url = bridge.openExternal.mock.calls[0]?.[0];
    if (typeof url !== "string") throw new Error("authorize url not opened");
    const state = new URL(url).searchParams.get("state");
    if (!state) throw new Error("no state in the authorize url");
    return state;
  }

  async function authorizeOpened(): Promise<void> {
    await vi.waitFor(() => expect(bridge.openExternal).toHaveBeenCalled());
  }

  it("rejects a callback whose state does not match and tears the loopback down", async () => {
    const { loopback, hit, cancel } = fakeLoopback();
    bridge.oauthLoopback = loopback;
    const login = startNativeLogin();
    await authorizeOpened();

    hit("http://127.0.0.1:4242/cb?code=c&state=forged");
    await expect(login).rejects.toThrow("state mismatch");
    expect(cancel).toHaveBeenCalledWith(4242);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("ignores stray hits without a code and settles on the first real callback only", async () => {
    const { loopback, hit, cancel } = fakeLoopback();
    bridge.oauthLoopback = loopback;
    // The success path full-navigates; jsdom reports that as a not-implemented
    // console error rather than throwing, so keep the log clean.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    fetchMock
      .mockResolvedValueOnce(
        tokenResponse({ access_token: "cp-tok", url: "https://box.example" }),
      )
      .mockResolvedValueOnce(
        tokenResponse({
          access_token: "at",
          refresh_token: "rt",
          expires_in: 3600,
        }),
      );
    const login = startNativeLogin();
    await authorizeOpened();
    const state = sentState();

    hit("http://127.0.0.1:4242/favicon.ico");
    hit(`http://127.0.0.1:4242/cb?code=c&state=${state}`);
    hit(`http://127.0.0.1:4242/cb?code=c&state=${state}`);
    await expect(login).resolves.toBeUndefined();

    expect(setConnection).toHaveBeenCalledTimes(1);
    expect(setConnection).toHaveBeenCalledWith(
      "https://box.example",
      "at",
      "rt",
      3600,
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(cancel).toHaveBeenCalledTimes(1);
  });
});
