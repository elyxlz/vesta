import { expect, it, vi } from "vitest";
import { Button, ButtonGroup } from "./Button";
import { radii } from "@/theme/layout";

vi.mock("react-native", () => ({
  Pressable: "Pressable",
  View: "View",
  StyleSheet: { create: <T>(styles: T) => styles },
}));
vi.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
vi.mock("expo-haptics", () => ({
  impactAsync: vi.fn(),
  ImpactFeedbackStyle: { Light: "light" },
}));
vi.mock("./Typography", () => ({ Text: "Text" }));
vi.mock("@/components/loading-spinner", () => ({
  LoadingSpinner: "LoadingSpinner",
}));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({
    colors: { accent: "#d5b993", accentText: "#26211a" },
  }),
}));

it("uses the provider sign-in appearance for a default primary action", () => {
  const button = Button({ children: "Connect", onPress: vi.fn() });
  const surface = Object.assign({}, ...button.props.style({ pressed: false }));
  const content = button.props.children({ pressed: false });
  const label = content.props.children[1];

  expect(surface).toMatchObject({
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: "#d5b993",
    opacity: 1,
  });
  expect(Object.assign({}, ...label.props.style)).toMatchObject({
    fontSize: 16,
    fontWeight: "600",
    color: "#26211a",
  });
});

it("keeps the primary surface while showing progress and blocking repeat presses", () => {
  const button = Button({
    children: "Connect",
    loading: true,
    loadingLabel: "Connecting…",
    onPress: vi.fn(),
  });
  const content = button.props.children({ pressed: false });

  expect(button.props.disabled).toBe(true);
  expect(content.props.children[0].type).toBe("LoadingSpinner");
  expect(content.props.children[1].props.children).toBe("Connecting…");
  expect(
    Object.assign({}, ...button.props.style({ pressed: false })),
  ).toMatchObject({
    minHeight: 48,
    borderRadius: radii.pill,
    backgroundColor: "#d5b993",
    opacity: 1,
  });
});

it.each([
  "primary",
  "secondary",
  "card",
  "cardDanger",
  "ghost",
  "danger",
  "plain",
] as const)("keeps %s buttons pill-shaped in every size and state", (variant) => {
  for (const size of ["default", "large", "small", "compact"] as const) {
    for (const state of [{}, { disabled: true }, { loading: true }]) {
      const button = Button({
        children: "Action",
        onPress: vi.fn(),
        variant,
        size,
        ...state,
      });
      for (const pressed of [false, true]) {
        const surface = Object.assign({}, ...button.props.style({ pressed }));
        expect(surface.borderRadius).toBe(radii.pill);
        expect(surface.borderRadius).toBeGreaterThanOrEqual(
          surface.minHeight / 2,
        );
        if (variant === "primary") {
          const label = button.props.children({ pressed }).props.children[1];
          expect(Object.assign({}, ...label.props.style).fontWeight).toBe("600");
        }
      }
    }
  }
});

it("spaces grouped actions without a rectangular enclosing surface", () => {
  const group = ButtonGroup({ children: ["Start agent", "Restart agent"] });
  expect(group.props.style.gap).toBeGreaterThan(0);
  expect(group.props.style).not.toHaveProperty("backgroundColor");
  expect(group.props.style).not.toHaveProperty("borderWidth");
  expect(group.props.children).toEqual(["Start agent", "Restart agent"]);
});
