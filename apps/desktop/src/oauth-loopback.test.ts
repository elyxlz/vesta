import { afterEach, describe, expect, it } from "vitest";
import { cancelLoopback, startLoopback } from "./oauth-loopback";

let port = 0;

afterEach(() => {
  cancelLoopback(port);
});

describe("oauth loopback", () => {
  it("reconstructs the full callback url from the incoming request", async () => {
    const captured: string[] = [];
    port = await startLoopback((url) => {
      captured.push(url);
    });
    const target = `http://127.0.0.1:${String(port)}/callback?code=abc&state=xyz`;

    expect(await (await fetch(target)).text()).toContain("Signed in");
    expect(captured).toEqual([target]);
  });

  it("frees the port after cancel", async () => {
    port = await startLoopback(() => undefined);
    cancelLoopback(port);
    await expect(fetch(`http://127.0.0.1:${String(port)}/`)).rejects.toBeTruthy();
  });
});
