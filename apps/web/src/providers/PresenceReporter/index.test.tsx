import { act, cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePreferences } from "@/stores/use-preferences";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import { fakeController, fakeTree } from "@/test/fake-controller";
import { PresenceReporter } from "./index";

const focus = vi.hoisted(() => ({ value: true }));
vi.mock("./use-window-focus", () => ({
  useWindowFocus: () => focus.value,
}));

// A router stub the test can navigate: the reporter reads the matched `agent/:name` and
// `chat/:roomId` params and re-reads them on every router notification.
const routerStub = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const state = {
    matches: [] as { params: { name?: string; roomId?: string } }[],
  };
  const set = (params: { name?: string; roomId?: string } | null) => {
    state.matches = params ? [{ params }] : [];
    for (const listener of listeners) listener();
  };
  return {
    state,
    listeners,
    navigate: (agent: string | null) => {
      set(agent === null ? null : { name: agent });
    },
    navigateRoom: (roomId: string) => {
      set({ roomId });
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
  usePreferences.setState({ shareLocation: true });
});

afterEach(() => {
  cleanup();
});

describe("PresenceReporter", () => {
  // A focused window on an agent page reports all three facts vestad reads: focus (push muting),
  // the viewed room (the presence nudge), and the device context (zone, read live; no geolocation
  // in this environment, so the stored position stands).
  it("reports focus, the viewed room, and the device context on a focus edge", async () => {
    const fake = fakeController(fakeTree());
    mount(fake);

    expect(fake.reports.presence).toHaveBeenLastCalledWith(true);
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("dm:ada");
    await waitFor(() => {
      expect(fake.reports.deviceContext.mock.calls).toEqual([
        [{ timezone: OS_ZONE }],
      ]);
    });
  });

  it("retracts the position when this device's sharing is switched off", async () => {
    usePreferences.setState({ shareLocation: false });
    const fake = fakeController(fakeTree());
    mount(fake);

    await waitFor(() => {
      expect(fake.reports.deviceContext.mock.calls).toEqual([
        [{ timezone: OS_ZONE, position: null }],
      ]);
    });
  });

  // A blurred window is viewing no one and reads no context; only focus itself is reported.
  // The open page is still reported while blurred (the socket masks it to null on the wire);
  // only the context read waits for focus.
  it("reports unfocused and the open page while blurred, and reads no context", () => {
    focus.value = false;
    const fake = fakeController(fakeTree());
    mount(fake);

    expect(fake.reports.presence).toHaveBeenLastCalledWith(false);
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("dm:ada");
    expect(fake.reports.deviceContext).not.toHaveBeenCalled();
  });

  // An agent page reports that agent's own direct room; the room route reports the room it names;
  // anywhere else reports nothing.
  it("follows the router to the newly opened conversation, and to none off one", () => {
    const fake = fakeController(fakeTree());
    mount(fake);

    act(() => {
      routerStub.navigate("grace");
    });
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("dm:grace");

    act(() => {
      routerStub.navigateRoom("grp-trip");
    });
    expect(fake.reports.viewing).toHaveBeenLastCalledWith("grp-trip");

    act(() => {
      routerStub.navigate(null);
    });
    expect(fake.reports.viewing).toHaveBeenLastCalledWith(null);
  });
});
