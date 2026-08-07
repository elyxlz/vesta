import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import { Dashboard } from "./index";

const mintKey = vi.fn<(agent: string, service: string) => Promise<string>>();

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({
    name: "bob",
    agent: { services: { dashboard: { port: 9100, rev: 0 } } },
  }),
}));

vi.mock("@/providers/ThemeProvider", () => ({
  useTheme: () => ({ resolvedTheme: "light" }),
}));

vi.mock("@/lib/connection", () => ({
  getConnection: () => ({
    url: "https://gateway.test",
    accessToken: "access-token",
  }),
}));

vi.mock("@/lib/service-key-cache", () => ({
  serviceKeys: {
    get: (agent: string, service: string) => mintKey(agent, service),
  },
}));

function frame(): HTMLIFrameElement | null {
  return document.querySelector("iframe");
}

// A mint the test resolves by hand, so the frame's state while the key is in flight is observable.
function pendingMint(): {
  promise: Promise<string>;
  resolve: (key: string) => void;
} {
  let resolve: (key: string) => void = () => undefined;
  const promise = new Promise<string>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

describe("Dashboard", () => {
  beforeEach(() => {
    mintKey.mockReset();
  });
  afterEach(cleanup);

  it("mounts no frame until the dashboard service key is minted", async () => {
    const mint = pendingMint();
    mintKey.mockReturnValue(mint.promise);

    render(<Dashboard />);
    expect(frame()).toBeNull();

    mint.resolve("deadbeef");

    await waitFor(() => {
      expect(frame()).not.toBeNull();
    });
    expect(frame()?.getAttribute("src")).toBe(
      "https://gateway.test/agents/bob/dashboard/k/deadbeef/",
    );
    expect(mintKey).toHaveBeenCalledWith("bob", "dashboard");
  });

  it("reports the dashboard unavailable when the mint fails", async () => {
    mintKey.mockRejectedValue(new Error("403 forbidden"));

    render(<Dashboard />);

    await waitFor(() => {
      expect(screen.getByText("dashboard unavailable")).toBeTruthy();
    });
    expect(frame()).toBeNull();
  });
});
