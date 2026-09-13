import { afterEach, expect, it, vi } from "vitest";
import { SheetChrome } from "./sheet-chrome.android";

const { dismissTo, popBack, canGoBack } = vi.hoisted(() => ({
  dismissTo: vi.fn(),
  popBack: vi.fn(),
  canGoBack: vi.fn(() => false),
}));

vi.mock("react-native", () => ({
  Pressable: "Pressable",
  Text: "Text",
  View: "View",
  StyleSheet: { create: <T>(styles: T) => styles },
}));
vi.mock("@expo/vector-icons", () => ({ Ionicons: "Ionicons" }));
vi.mock("expo-router", () => ({
  useRouter: () => ({ dismissTo, back: popBack, canGoBack }),
}));
vi.mock("expo-router/stack", () => ({
  default: {
    Screen: "Stack.Screen",
    Title: "Stack.Title",
    Toolbar: Object.assign("Stack.Toolbar", { Button: "Stack.Toolbar.Button" }),
  },
}));
vi.mock("@/agent/AgentProvider", () => ({
  useAgent: () => ({ name: "aria", agent: null, activityState: null }),
}));
vi.mock("@/components/AgentOrb", () => ({ AgentOrb: "AgentOrb" }));
vi.mock("@/components/BootTransition", () => ({
  BootTransitionTarget: "BootTransitionTarget",
}));
vi.mock("@/components/ui/glass-surface", () => ({ GlassSurface: "GlassSurface" }));
vi.mock("@/components/ui/Typography", () => ({ Text: "Text" }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({
    colors: { text: "black", elevated: "#f4f1ed", border: "#ccc" },
  }),
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

it("gives the Android back button the same flat surface as sheet close", async () => {
  vi.stubEnv("EXPO_OS", "android");
  vi.resetModules();
  const { AgentStackHeader } = await import("./AgentHeader");
  const header = AgentStackHeader({});
  const element = header.props.children[0].props.options.headerLeft();
  const back = element.type(element.props);
  const close = SheetChrome({
    title: "Settings",
    closeLabel: "Close settings",
  }).props.children[1].props.children[1];
  const backStyle = Object.assign({}, ...back.props.style);
  const closeStyle = Object.assign({}, ...close.props.style);

  for (const key of [
    "width",
    "height",
    "borderRadius",
    "borderCurve",
    "backgroundColor",
  ]) {
    expect(backStyle[key]).toBe(closeStyle[key]);
  }
  expect(backStyle).not.toHaveProperty("boxShadow");
  expect(backStyle.backgroundColor).toBe("#f4f1ed");
  expect(backStyle).not.toHaveProperty("elevation");
  expect(back.props.android_ripple).toEqual(close.props.android_ripple);
  expect(back.props.accessibilityLabel).toBe("Back");
  expect(back.props.children.props.name).toBe("chevron-back");
  back.props.onPress();
  expect(dismissTo).toHaveBeenCalledWith("/");
});

it("pops back to the screen the agent page was opened from", async () => {
  vi.stubEnv("EXPO_OS", "android");
  vi.resetModules();
  canGoBack.mockReturnValue(true);
  const { AgentStackHeader } = await import("./AgentHeader");
  const header = AgentStackHeader({});
  const element = header.props.children[0].props.options.headerLeft();
  element.type(element.props).props.onPress();
  expect(popBack).toHaveBeenCalledOnce();
  expect(dismissTo).not.toHaveBeenCalled();
});

it("keeps the iOS native back toolbar unchanged", async () => {
  vi.stubEnv("EXPO_OS", "ios");
  vi.resetModules();
  const { AgentStackHeader } = await import("./AgentHeader");
  const header = AgentStackHeader({});

  expect(header.props.children[0].props.options.headerLeft).toBeUndefined();
  expect(header.props.children[2].props.children.props.icon).toBe(
    "chevron.backward",
  );
});
