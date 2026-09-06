import { afterEach, expect, it, vi } from "vitest";
import ScanScreen from "../../app/(connect)/scan";

vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useEffect: vi.fn(),
  useState: () => [false, vi.fn()],
}));
vi.mock("react-native", () => ({
  View: "View",
  StyleSheet: { create: (styles: unknown) => styles },
}));
vi.mock("expo-camera", () => ({
  CameraView: "CameraView",
  useCameraPermissions: () => [{ granted: true }, vi.fn(), vi.fn()],
}));
vi.mock("expo-router", () => ({
  Stack: { Screen: "StackScreen" },
  useRouter: () => ({}),
}));
vi.mock("@/components/ui/Button", () => ({ Button: "Button" }));
vi.mock("@/components/ui/States", () => ({ LoadingState: "LoadingState" }));
vi.mock("@/components/ui/Typography", () => ({ Text: "Text" }));
vi.mock("@/components/native-sheet-close-button", () => ({
  NativeSheetCloseButton: "NativeSheetCloseButton",
}));
vi.mock("@/components/sheet-chrome", () => ({ SheetChrome: "SheetChrome" }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({ colors: { text: "black" }, dark: false }),
}));
vi.mock("@/privacy/use-privacy-blocked", () => ({ usePrivacyBlocked: () => false }));

afterEach(() => vi.unstubAllEnvs());

it.each(["ios", "android"])(
  "keeps the %s camera overlay tint separate from the opaque Android button",
  (platform) => {
    vi.stubEnv("EXPO_OS", platform);
    const screen = ScanScreen();
    const content = screen.type();
    const header = content.props.children[1];
    expect(header.props.children[0].props.options.headerTintColor).toBe("white");
    const chrome = header.props.children[2].props.children;
    expect(chrome.props.closeLabel).toBe("Close scanner");
    expect(chrome.props.tintColor).toBeUndefined();
    if (platform === "ios") {
      expect(header.props.children[1].props.tintColor).toBe("white");
    }
  },
);
