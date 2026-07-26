import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AppStateStatus } from "react-native";
import { createAppStateForegroundSignal } from "./foreground-signal";

type ChangeListener = (state: AppStateStatus) => void;

const { appState, remove } = vi.hoisted(() => {
  const remove = vi.fn<() => void>();
  return {
    remove,
    appState: {
      currentState: "active" as AppStateStatus,
      changeListener: null as ChangeListener | null,
      addEventListener: vi.fn(
        (_event: string, listener: ChangeListener): { remove: () => void } => {
          appState.changeListener = listener;
          return { remove };
        },
      ),
    },
  };
});

vi.mock("react-native", () => ({ AppState: appState }));

beforeEach(() => {
  appState.currentState = "active";
  appState.changeListener = null;
  appState.addEventListener.mockClear();
  remove.mockClear();
});

describe("createAppStateForegroundSignal", () => {
  it("reflects the current AppState in isForeground", () => {
    const signal = createAppStateForegroundSignal();

    appState.currentState = "active";
    expect(signal.isForeground()).toBe(true);

    appState.currentState = "inactive";
    expect(signal.isForeground()).toBe(true);

    appState.currentState = "background";
    expect(signal.isForeground()).toBe(false);
  });

  it("keeps transient inactive transitions alive and closes only in background", () => {
    const signal = createAppStateForegroundSignal();
    const listener = vi.fn();
    signal.subscribe(listener);

    appState.changeListener?.("active");
    appState.changeListener?.("inactive");
    appState.changeListener?.("background");

    expect(listener.mock.calls).toEqual([[true], [true], [false]]);
  });

  it("removes the subscription when the disposer runs", () => {
    const signal = createAppStateForegroundSignal();

    const dispose = signal.subscribe(vi.fn());
    dispose();

    expect(remove).toHaveBeenCalledOnce();
  });
});
