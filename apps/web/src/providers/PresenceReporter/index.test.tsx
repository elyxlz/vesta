import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useShareLocation } from "@/stores/use-share-location";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import { fakeController, fakeTree } from "@/test/fake-controller";
import { PresenceReporter } from "./index";

const focus = vi.hoisted(() => ({ value: true }));
vi.mock("@/hooks/use-window-focus", () => ({
  useWindowFocus: () => focus.value,
}));

// A router stub the test can navigate: the reporter reads the matched `agent/:name` param and
// re-reads it on every router notification.
const routerStub = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const state = { matches: [] as { params: { name?: string } }[] };
  return {
    state,
    listeners,
    navigate: (agent: string | null) => {
      state.matches = agent ? [{ params: { name: agent } }] : [];
      for (const listener of listeners) listener();
    },
  };
});
vi.mock("@/router", () => ({
  router: {
    state: routerStub.state,
    subscribe: (listener: () => void) => {
      routerStub.listeners.add(listener);
      return () => routerStub.listeners.delete(listener);
    },
  },
}));

const OS_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

function mount(fake: ReturnType<typeof fakeController>) {
  return render(
    <ControllerContext.Provider value={fake.controller}>
      <PresenceReporter />
    </ControllerContext.Provider>,
  );
}

beforeEach(() => {
  focus.value = true;
  routerStub.navigate("ada");
  useShareLocation.setState({ enabled: true });
});

afterEach(() => {
  cleanup();
});

describe("PresenceReporter", () => {
  // A focused window on an agent page reports all three facts vestad reads: focus (push muting),
  // the viewed agent (the presence nudge), and the device context (zone, read live; no geolocation
  // in this environment, so the stored position stands).
  it("reports focus, the viewed agent, and the device context on a focus edge", async () => {
    const fake = fakeController(fakeTree());
    mount(fake);

    expect(fake.reports.presence).toHaveBeenLastCalledWith(true);
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("ada");
    await waitFor(() => {
      expect(fake.reports.deviceContext.mock.calls).toEqual([
        [{ timezone: OS_ZONE }],
      ]);
    });
  });

  it("retracts the position when this device's sharing is switched off", async () => {
    useShareLocation.setState({ enabled: false });
    const fake = fakeController(fakeTree());
    mount(fake);

    await waitFor(() => {
      expect(fake.reports.deviceContext.mock.calls).toEqual([
        [{ timezone: OS_ZONE, position: null }],
      ]);
    });
  });

  // A blurred window is viewing no one and reads no context; only focus itself is reported.
  it("reports unfocused and no viewed agent while blurred, and reads no context", () => {
    focus.value = false;
    const fake = fakeController(fakeTree());
    mount(fake);

    expect(fake.reports.presence).toHaveBeenLastCalledWith(false);
    expect(fake.reports.viewing).toHaveBeenLastCalledWith(null);
    expect(fake.reports.deviceContext).not.toHaveBeenCalled();
  });

  it("follows the router to the newly opened agent, and to none off an agent page", () => {
    const fake = fakeController(fakeTree());
    mount(fake);

    act(() => {
      routerStub.navigate("grace");
    });
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("grace");

    act(() => {
      routerStub.navigate(null);
    });
    expect(fake.reports.viewing).toHaveBeenLastCalledWith(null);
  });
});
