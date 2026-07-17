import { afterEach, describe, expect, it } from "vitest";
import { cancelLoopback, startLoopback } from "./oauth-loopback";

const openPorts: number[] = [];

afterEach(() => {
  for (const port of openPorts.splice(0)) cancelLoopback(port);
});

describe("oauth loopback", () => {
  it("reconstructs the full callback url from the incoming request", async () => {
    const captured: string[] = [];
    const port = await startLoopback((url) => {
      captured.push(url);
    });
    openPorts.push(port);

    const response = await fetch(
      `http://127.0.0.1:${String(port)}/callback?code=abc&state=xyz`,
    );

    expect(response.status).toBe(200);
    expect(await response.text()).toContain("Signed in");
    expect(captured).toEqual([
      `http://127.0.0.1:${String(port)}/callback?code=abc&state=xyz`,
    ]);
  });

  it("frees the port after cancel", async () => {
    const port = await startLoopback(() => {
      /* never called */
    });
    cancelLoopback(port);
    await expect(fetch(`http://127.0.0.1:${String(port)}/`)).rejects.toBeTruthy();
  });
});
