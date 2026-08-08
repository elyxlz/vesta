import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { AgentRow, GatewayOperation } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { NavigationGuard } from "./index";

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({ connected: true, initialized: true }),
}));

const ADA: AgentRow = {
  name: "ada",
  status: "alive",
  activityState: "idle",
  buildPhase: null,
  operation: null,
  startedAt: null,
  services: {},
};

const RUNNING: GatewayOperation = {
  kind: "update",
  phase: "applying",
  agent: null,
  done: null,
  total: null,
  targetVersion: "0.1.190",
  warnings: [],
  error: null,
};

function renderAt(path: string, overrides: Partial<GatewayContextValue>) {
  const value: GatewayContextValue = {
    ...disconnectedValue,
    agentsFetched: true,
    agents: [ADA],
    ...overrides,
  };
  return render(
    <GatewayContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route element={<NavigationGuard />}>
            <Route index element={<p>home</p>} />
            <Route path="settings" element={<p>settings</p>} />
            <Route path="agent/:name" element={<p>agent</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </GatewayContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("NavigationGuard", () => {
  it("leaves navigation alone while the gateway is idle", () => {
    const { getByText } = renderAt("/agent/ada", {});
    expect(getByText("agent")).toBeTruthy();
  });

  it("sends agent pages home while a gateway update runs", () => {
    const { getByText } = renderAt("/agent/ada", { gatewayOperation: RUNNING });
    expect(getByText("home")).toBeTruthy();
  });

  it("keeps settings reachable during an update, since that is where a stuck one is diagnosed", () => {
    const { getByText } = renderAt("/settings", { gatewayOperation: RUNNING });
    expect(getByText("settings")).toBeTruthy();
  });

  it("stays home during an update with zero agents instead of ping-ponging with the /new redirect", () => {
    const { getByText } = renderAt("/", {
      agents: [],
      gatewayOperation: RUNNING,
    });
    expect(getByText("home")).toBeTruthy();
  });
});
