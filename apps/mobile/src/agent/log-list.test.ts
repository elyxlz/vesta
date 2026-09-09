import { afterEach, expect, it, vi } from "vitest";
import { LogList } from "./log-list";

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useMemo: (factory: () => unknown) => factory(),
  useCallback: (callback: unknown) => callback,
  useRef: (current: unknown) => ({ current }),
  useState: (initial: unknown) => [initial, vi.fn()],
}));
vi.mock("react-native", () => ({
  FlatList: "FlatList",
  View: "View",
  StyleSheet: { create: <T>(styles: T) => styles },
}));
vi.mock("react-native-safe-area-context", () => ({
  SafeAreaProvider: "SafeAreaProvider",
  useSafeAreaInsets: () => ({ top: 44, bottom: 34, left: 0, right: 0 }),
}));
vi.mock("@/components/ui/AnsiText", () => ({ AnsiText: "AnsiText" }));
vi.mock("@/components/ui/Typography", () => ({ Text: "Text" }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({ colors: {} }),
}));
vi.mock("./use-bottom-anchored-feed", () => ({
  useBottomAnchoredFeed: () => ({ contentVisible: true }),
}));

afterEach(() => vi.unstubAllEnvs());

it.each(["ios", "android"])(
  "keeps %s standalone log content inside the bottom safe area in every state",
  (platform) => {
    vi.stubEnv("EXPO_OS", platform);
    for (const state of [
      { logs: [], logError: "" },
      { logs: [], logError: "disconnected" },
      { logs: [{ id: 1, text: "ready" }], logError: "" },
    ]) {
      const screen = LogList({ ...state, presentation: "standalone" });
      const content = platform === "ios" ? screen.props.children : screen;
      if (platform === "ios") expect(screen.type).toBe("SafeAreaProvider");
      const viewport = content.type(content.props);
      const list = viewport.props.children;
      expect(Object.assign({}, ...viewport.props.style).paddingBottom).toBe(34);
      expect(list.props.contentInsetAdjustmentBehavior).toBe("never");
      expect(list.props.automaticallyAdjustContentInsets).toBe(false);
      expect(Object.assign({}, ...list.props.contentContainerStyle)).toMatchObject({
        paddingTop: platform === "ios" ? 56 : 12,
        paddingBottom: 12,
        justifyContent: "flex-end",
      });
    }
  },
);

it("preserves the inverted pager's existing inset handling", () => {
  vi.stubEnv("EXPO_OS", "ios");
  const content = LogList({ logs: [], logError: "", presentation: "pager" });
  const list = content.type(content.props).props.children;
  expect(list.props.inverted).toBe(true);
  expect(list.props.contentInsetAdjustmentBehavior).toBe("never");
  expect(Object.assign({}, ...list.props.contentContainerStyle)).toMatchObject({
    paddingTop: 34,
    paddingBottom: 148,
  });
});
