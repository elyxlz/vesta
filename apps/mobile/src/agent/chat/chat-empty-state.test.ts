import { describe, expect, it, vi } from "vitest";
import type { SharedValue } from "react-native-reanimated";
import { ChatEmptyState } from "./chat-empty-state";

vi.mock("react-native", () => ({
  View: "View",
  StyleSheet: { create: (styles: unknown) => styles },
}));
vi.mock("react-native-reanimated", () => ({
  default: { View: "AnimatedView" },
  useAnimatedStyle: (style: () => unknown) => style(),
}));
vi.mock("react-native-keyboard-controller", () => ({
  KeyboardStickyView: "KeyboardStickyView",
}));
vi.mock("@/components/ui/Typography", () => ({ Text: "Text" }));
vi.mock("@/preferences/PreferencesProvider", () => ({
  usePreferences: () => ({ colors: { text: "black", secondaryText: "gray" } }),
}));

describe("empty conversation insets", () => {
  it.each([0, 96, 120, 240])(
    "reserves the measured composer inset of %i without adding safe area twice",
    (inset) => {
      const tree = ChatEmptyState({
        agentName: "nova",
        composerInset: { value: inset } as SharedValue<number>,
        keyboardOffset: 32,
      });
      expect(tree.props.style).toMatchObject({
        position: "absolute",
        bottom: 0,
      });
      expect(tree.props.children.props.style).toEqual({ paddingBottom: inset });
      expect(tree.props.children.props.children.props.style).toMatchObject({
        minHeight: 300,
        justifyContent: "center",
      });
      expect(tree.props.offset).toEqual({ closed: 0, opened: 32 });
      expect(tree.props.pointerEvents).toBe("none");
    },
  );
});
