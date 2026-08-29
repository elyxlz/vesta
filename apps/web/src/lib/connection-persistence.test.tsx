// Exercises localStorage, so it runs in the jsdom project (.test.tsx include).
import { afterEach, describe, expect, it, vi } from "vitest";
import { getConnection, setConnection } from "./connection";
import { native } from "./native";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("connection persistence", () => {
  it("keeps a connected session when persistent storage throws", async () => {
    const warning = vi
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {
      throw new Error("storage unavailable");
    });

    expect(() =>
      setConnection("https://box.example/", "access", "refresh", 60),
    ).not.toThrow();
    expect(getConnection()).toMatchObject({
      url: "https://box.example",
      accessToken: "access",
      refreshToken: "refresh",
    });

    await vi.waitFor(() => {
      expect(warning).toHaveBeenCalledWith(
        "could not save the active gateway",
        expect.any(Error),
      );
    });
  });

  it("keeps a connected session when an Electron-style write rejects", async () => {
    const warning = vi
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    vi.spyOn(native.connectionStore, "write").mockRejectedValueOnce(
      new Error("secure storage unavailable"),
    );

    setConnection("https://box.example", "access", "refresh", 60);
    expect(getConnection()?.accessToken).toBe("access");

    await vi.waitFor(() => {
      expect(warning).toHaveBeenCalledWith(
        "could not save the active gateway",
        expect.any(Error),
      );
    });
  });
});
