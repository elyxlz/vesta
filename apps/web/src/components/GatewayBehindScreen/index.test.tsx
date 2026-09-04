import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GatewayOperation } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { GatewayBehindScreen } from "./index";

// The gateway-behind takeover is reached only by a client ahead of its gateway (desktop/mobile),
// never the browser, so its progress rendering has no other coverage. Mock the navbar and the
// progress screen to markers and assert which branch the screen routes to.
vi.mock("@/providers/AuthProvider/context", () => ({
  useAuth: () => ({ disconnect: () => undefined }),
}));
vi.mock("@/components/Navbar", () => ({
  Navbar: () => <div data-testid="navbar" />,
}));
vi.mock("@/components/UpdateProgressScreen", () => ({
  UpdateProgressScreen: () => <div data-testid="update-progress" />,
}));

afterEach(cleanup);

const RUNNING: GatewayOperation = {
  kind: "update",
  phase: "snapshotting",
  agent: null,
  done: null,
  total: null,
  targetVersion: "0.3.4",
  warnings: [],
  error: null,
};

function mount(overrides: Partial<GatewayContextValue>) {
  return render(
    <GatewayContext.Provider value={{ ...disconnectedValue, ...overrides }}>
      <GatewayBehindScreen />
    </GatewayContext.Provider>,
  );
}

describe("GatewayBehindScreen", () => {
  it("offers the update button while the gateway is idle", () => {
    mount({ gatewayOperation: null, updatedTo: null });
    expect(
      screen.getByRole("button", { name: /update gateway/i }),
    ).toBeTruthy();
    expect(screen.queryByTestId("update-progress")).toBeNull();
  });

  it("renders live update progress once the operation is running", () => {
    mount({ gatewayOperation: RUNNING });
    expect(screen.getByTestId("update-progress")).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: /update gateway/i }),
    ).toBeNull();
  });

  it("keeps the progress screen for the post-update landing notice", () => {
    mount({ gatewayOperation: null, updatedTo: "0.3.4" });
    expect(screen.getByTestId("update-progress")).toBeTruthy();
  });
});
