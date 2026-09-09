import { describe, expect, it, vi } from "vitest";
import { ReadyScreen } from "../visual/harness/ready-screen";

const phase = vi.hoisted(() => ({ active: false }));
vi.mock("react-native", () => ({ View: "View" }));
vi.mock("../src/components/BootTransition", () => ({
  useBootTransitionPhase: () => phase,
}));

describe("visual screen readiness", () => {
  it("exposes a non-interactive marker after boot without changing the screen", () => {
    phase.active = false;
    const screen = ReadyScreen({ children: "production screen" });
    const [children, marker] = screen.props.children;
    expect(children).toBe("production screen");
    expect(marker.props).toMatchObject({
      testID: "visual-harness-ready",
      pointerEvents: "none",
      collapsable: false,
      style: { position: "absolute", width: 1, height: 1 },
    });
  });

  it("withholds the signal while the boot handoff is active", () => {
    phase.active = true;
    expect(ReadyScreen({ children: "screen" }).props.children).toEqual([
      "screen",
      false,
    ]);
    phase.active = false;
  });
});
