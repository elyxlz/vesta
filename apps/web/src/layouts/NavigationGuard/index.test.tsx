import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { GatewayOperation } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { fakeAgentRow } from "@/test/fake-controller";
import { clearOnboarding, saveOnboarding } from "@/lib/onboarding-progress";
import { NavigationGuard } from "./index";

const auth = vi.hoisted(() => ({ connected: true }));
vi.mock("@/providers/AuthProvider/context", () => ({
  useAuth: () => ({ connected: auth.connected, initialized: true }),
}));

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
    agents: [fakeAgentRow("ada")],
    ...overrides,
  };
  return render(
    <GatewayContext.Provider value={value}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="connect" element={<p>connect</p>} />
          <Route element={<NavigationGuard />}>
            <Route index element={<p>home</p>} />
            <Route path="new" element={<p>new</p>} />
            <Route path="settings" element={<p>settings</p>} />
            <Route path="agent/:name/*" element={<p>agent</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </GatewayContext.Provider>,
  );
}

beforeEach(() => {
  auth.connected = true;
});

afterEach(() => {
  cleanup();
  clearOnboarding();
});

describe("NavigationGuard", () => {
  it("leaves navigation alone while the gateway is idle", () => {
    const { getByText } = renderAt("/agent/ada", {});
    expect(getByText("agent")).toBeTruthy();
  });

  it("sends a disconnected client to the connect screen", () => {
    auth.connected = false;
    const { getByText } = renderAt("/agent/ada", {});
    expect(getByText("connect")).toBeTruthy();
  });

  it("sends agent pages home while a gateway update runs", () => {
    const { getByText } = renderAt("/agent/ada", { gatewayOperation: RUNNING });
    expect(getByText("home")).toBeTruthy();
  });

  it("keeps settings reachable during an update, since that is where a stuck one is diagnosed", () => {
    const { getByText } = renderAt("/settings", { gatewayOperation: RUNNING });
    expect(getByText("settings")).toBeTruthy();
  });

  it("sends an empty, fetched roster to the new-agent page", () => {
    const { getByText } = renderAt("/", { agents: [] });
    expect(getByText("new")).toBeTruthy();
  });

  // Before the snapshot lands the roster is unknown, not empty: no redirect flashes on a fresh socket.
  it("stays put while the roster is not yet fetched", () => {
    const { getByText } = renderAt("/", { agents: [], agentsFetched: false });
    expect(getByText("home")).toBeTruthy();
  });

  it("stays home during an update with zero agents instead of ping-ponging with the /new redirect", () => {
    const { getByText } = renderAt("/", {
      agents: [],
      gatewayOperation: RUNNING,
    });
    expect(getByText("home")).toBeTruthy();
  });

  it.each([
    ["unprovisioned", { status: "unprovisioned" as const, booting: false }],
    ["starting", { status: "starting" as const, booting: false }],
    ["booting", { status: "alive" as const, booting: true }],
  ])(
    "keeps the onboarding agent behind the new-agent screen while %s",
    (_, state) => {
      saveOnboarding({ agentName: "ada", personality: null });
      const { getByText, queryByText } = renderAt("/agent/ada/chat", {
        agents: [fakeAgentRow("ada", state)],
      });
      expect(getByText("new")).toBeTruthy();
      expect(queryByText("agent")).toBeNull();
    },
  );

  it("opens the onboarding agent only after the ready state is observed", () => {
    saveOnboarding({ agentName: "ada", personality: null });
    const { getByText } = renderAt("/agent/ada/chat", {
      agents: [fakeAgentRow("ada", { status: "alive", booting: false })],
    });
    expect(getByText("agent")).toBeTruthy();
  });

  it("does not contain an unrelated agent while onboarding is active", () => {
    saveOnboarding({ agentName: "ada", personality: null });
    const { getByText } = renderAt("/agent/grace/chat", {
      agents: [
        fakeAgentRow("ada", { status: "starting", booting: false }),
        fakeAgentRow("grace", { status: "alive", booting: false }),
      ],
    });
    expect(getByText("agent")).toBeTruthy();
  });
});
