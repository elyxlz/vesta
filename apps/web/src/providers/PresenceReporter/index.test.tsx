import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useShareLocation } from "@/stores/use-share-location";
import type { Controller } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { PresenceReporter } from "./index";

const focus = vi.hoisted(() => ({ value: true }));
vi.mock("@/hooks/use-window-focus", () => ({
  useWindowFocus: () => focus.value,
}));
vi.mock("@/router", () => ({
  router: { state: { matches: [] }, subscribe: () => () => undefined },
}));

function fakeController() {
  const reports: unknown[] = [];
  const controller = {
    reportPresence: () => undefined,
    reportViewing: () => undefined,
    reportDeviceContext: (context: unknown) => {
      reports.push(context);
    },
  } as unknown as Controller;
  return { controller, reports };
}

describe("PresenceReporter", () => {
  it("reports the device timezone on a focus edge, read live", async () => {
    const { controller, reports } = fakeController();
    focus.value = true;
    render(
      <ControllerContext.Provider value={controller}>
        <PresenceReporter />
      </ControllerContext.Provider>,
    );
    // Sharing is on by default; with no geolocation in this environment the report names the OS
    // zone alone and the stored position stands.
    await waitFor(() => {
      expect(reports).toEqual([
        { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone },
      ]);
    });
  });

  it("retracts the position when this device's sharing is switched off", async () => {
    const { controller, reports } = fakeController();
    focus.value = true;
    useShareLocation.setState({ enabled: false });
    try {
      render(
        <ControllerContext.Provider value={controller}>
          <PresenceReporter />
        </ControllerContext.Provider>,
      );
      await waitFor(() => {
        expect(reports).toEqual([
          {
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            position: null,
          },
        ]);
      });
    } finally {
      useShareLocation.setState({ enabled: true });
    }
  });

  it("does not report a device context while blurred", () => {
    const { controller, reports } = fakeController();
    focus.value = false;
    render(
      <ControllerContext.Provider value={controller}>
        <PresenceReporter />
      </ControllerContext.Provider>,
    );
    expect(reports).toEqual([]);
  });
});
