import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GatewayUpdateOperation } from "@vesta/core";
import {
  GatewayContext,
  disconnectedValue,
  type GatewayContextValue,
} from "@/providers/GatewayProvider/context";
import { UpdatePill } from "./index";

function operation(
  overrides: Partial<GatewayUpdateOperation> = {},
): GatewayUpdateOperation {
  return {
    kind: "update",
    phase: "snapshotting",
    agent: "ada",
    done: 1,
    total: 4,
    targetVersion: "0.1.190",
    warnings: [],
    error: null,
    ...overrides,
  };
}

function renderPill(overrides: Partial<GatewayContextValue>) {
  const value: GatewayContextValue = { ...disconnectedValue, ...overrides };
  return render(
    <GatewayContext.Provider value={value}>
      <UpdatePill />
    </GatewayContext.Provider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("UpdatePill", () => {
  it("renders nothing with no update available and none running", () => {
    const { container } = renderPill({});
    expect(container.firstChild).toBeNull();
  });

  it("offers the update when one is available, naming the version", () => {
    const { getByRole } = renderPill({
      updateAvailable: true,
      latestVersion: "0.1.190",
    });
    const button = getByRole("button");
    expect(button.textContent).toBe("update");
    expect(button.getAttribute("title")).toBe("Update to v0.1.190");
    expect(button.hasAttribute("disabled")).toBe(false);
  });

  it("shows the live phase and refuses a second click while an update runs", () => {
    const { getByRole } = renderPill({ updateOperation: operation() });
    const button = getByRole("button");
    expect(button.textContent).toContain("updating");
    expect(button.getAttribute("title")).toBe("backing up ada 2/4");
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("offers a retry once an update has failed", () => {
    const { getByRole } = renderPill({
      updateOperation: operation({
        phase: "failed",
        error: "while installing: curl failed",
      }),
    });
    const button = getByRole("button");
    expect(button.textContent).toBe("retry");
    expect(button.hasAttribute("disabled")).toBe(false);
  });
});
