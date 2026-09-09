import { afterEach, describe, expect, it, vi } from "vitest";
import ConnectLayout, { unstable_settings } from "../../app/(connect)/_layout";

vi.mock("expo-router/stack", () => ({
  default: Object.assign(() => null, { Screen: () => null }),
}));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({
    colors: { background: "white", card: "white", text: "black" },
  }),
}));

describe("connection sheet navigation", () => {
  afterEach(() => vi.unstubAllEnvs());

  it.each(["ios", "android"])(
    "retains the landing backdrop on %s",
    (platform) => {
      vi.stubEnv("EXPO_OS", platform);
      const stack = ConnectLayout();
      expect(unstable_settings.anchor).toBe("connect");
      expect(stack.props.screenOptions.presentation).toBe("formSheet");
      expect(stack.props.children[0].props.options.presentation).toBe("card");
    },
  );

  it.each(["ios", "android"])(
    "keeps scanner chrome out of the %s system bar",
    (platform) => {
      vi.stubEnv("EXPO_OS", platform);
      const scanner = ConnectLayout().props.children.at(-1);
      expect(scanner.props.name).toBe("scan");
      expect(scanner.props.options.sheetAllowedDetents).toEqual(
        platform === "android" ? [0.92] : [1],
      );
      expect(scanner.props.options.headerShown).toBe(platform === "ios");
      expect(scanner.props.options.sheetExpandsWhenScrolledToEdge).toBe(false);
    },
  );
});
