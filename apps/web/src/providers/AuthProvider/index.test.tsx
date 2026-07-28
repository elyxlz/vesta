import { useEffect } from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RefreshResult } from "@/lib/token-refresh";
import { AuthProvider, useAuth } from "./index";

const mocks = vi.hoisted(() => ({
  clearConnection: vi.fn(),
  ensureFreshToken: vi.fn<() => Promise<RefreshResult>>(),
}));

vi.mock("@/api", () => ({
  connectToServer: vi.fn(),
}));

vi.mock("@/lib/connection", () => ({
  clearConnection: mocks.clearConnection,
  getConnection: () => ({
    url: "https://vestad.test",
    accessToken: "expired",
    refreshToken: "refresh",
    expiresAt: 0,
  }),
  initConnection: () => Promise.resolve(),
  isTokenExpiringSoon: () => true,
  parseConnectKey: () => null,
}));

vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: mocks.ensureFreshToken,
}));

function Probe({
  report,
}: {
  report: (state: { initialized: boolean; connected: boolean; sessionExpired: boolean }) => void;
}) {
  const { initialized, connected, sessionExpired } = useAuth();
  useEffect(() => {
    report({ initialized, connected, sessionExpired });
  }, [connected, initialized, report, sessionExpired]);
  return null;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AuthProvider startup refresh", () => {
  it("does not expose a stored session until its expiring token is refreshed", async () => {
    let resolveRefresh!: (result: RefreshResult) => void;
    mocks.ensureFreshToken.mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }),
    );
    const states: { initialized: boolean; connected: boolean }[] = [];

    render(
      <AuthProvider>
        <Probe report={(state) => states.push(state)} />
      </AuthProvider>,
    );

    await waitFor(() => expect(mocks.ensureFreshToken).toHaveBeenCalledOnce());
    expect(states.at(-1)).toMatchObject({ initialized: false, connected: false });

    resolveRefresh("ok");
    await waitFor(() =>
      expect(states.at(-1)).toMatchObject({ initialized: true, connected: true }),
    );
  });

  it("clears a stored session when startup refresh is rejected", async () => {
    mocks.ensureFreshToken.mockResolvedValue("expired");
    const states: {
      initialized: boolean;
      connected: boolean;
      sessionExpired: boolean;
    }[] = [];

    render(
      <AuthProvider>
        <Probe report={(state) => states.push(state)} />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(states.at(-1)).toEqual({
        initialized: true,
        connected: false,
        sessionExpired: true,
      }),
    );
    expect(mocks.clearConnection).toHaveBeenCalledOnce();
  });
});
