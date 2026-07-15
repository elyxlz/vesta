import { afterEach, describe, expect, it, vi } from "vitest";
import { connectWithKey } from "./auth";

vi.mock("expo-crypto", () => ({}));
vi.mock("expo-web-browser", () => ({}));

describe("gateway connection", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("stops waiting when an unreachable gateway never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () =>
              reject(new DOMException("Aborted", "AbortError")),
            );
          }),
      ),
    );

    const connection = connectWithKey("https://offline.vesta.run", "key");
    const result = expect(connection).rejects.toThrow(
      "Could not reach this Vesta gateway.",
    );
    await vi.runAllTimersAsync();
    await result;
  });
});
