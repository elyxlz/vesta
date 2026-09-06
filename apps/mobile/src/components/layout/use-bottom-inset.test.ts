import { afterEach, expect, it, vi } from "vitest";
import { isValidElement } from "react";

const { insets } = vi.hoisted(() => ({
  insets: { top: 24, right: 0, bottom: 48, left: 0 },
}));

vi.mock("react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react")>()),
  useMemo: (factory: () => unknown) => factory(),
}));
vi.mock("react-native-safe-area-context", () => ({
  SafeAreaInsetsContext: { Provider: "SafeAreaInsetsProvider" },
  useSafeAreaInsets: () => insets,
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

it.each([12, 24, 48, 64])(
  "keeps Android content above a %sdp navigation inset with separate breathing room",
  async (bottom) => {
    vi.stubEnv("EXPO_OS", "android");
    insets.bottom = bottom;
    const { AndroidBottomInset } = await import("./android-bottom-inset");
    const { useBottomInset } = await import("./use-bottom-inset");
    const provider = AndroidBottomInset({ children: "screen" });
    if (!isValidElement<{ value: typeof insets }>(provider)) {
      throw new Error("Android must provide its adjusted safe area");
    }

    expect(provider.props.value).toEqual({
      ...insets,
      bottom: Math.max(48, bottom),
    });
    insets.bottom = provider.props.value.bottom;
    expect(useBottomInset(24)).toBe(Math.max(48, bottom) + 24);
    expect(useBottomInset(0)).toBe(Math.max(48, bottom));
  },
);

it("leaves iOS sheet padding to its native safe-area handling", async () => {
  vi.stubEnv("EXPO_OS", "ios");
  insets.bottom = 34;
  const { AndroidBottomInset } = await import("./android-bottom-inset");
  const { useBottomInset } = await import("./use-bottom-inset");

  expect(AndroidBottomInset({ children: "screen" })).toBe("screen");
  expect(useBottomInset(24)).toBe(24);
  expect(useBottomInset(0)).toBe(0);
});
