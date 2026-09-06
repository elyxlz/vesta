import { describe, expect, it, vi } from "vitest";
import { darkColors, lightColors } from "@/theme/colors";
import { chatMarkdownStyleSet } from "./chat-markdown";

vi.mock("react-native", () => ({ StyleSheet: { hairlineWidth: 1 } }));

describe("chat markdown contrast", () => {
  it.each([lightColors, darkColors])(
    "uses the accent foreground for quotes inside outgoing bubbles",
    (colors) => {
      const styles = chatMarkdownStyleSet(colors);
      expect(styles.user.blockquote.color).toBe(colors.accentText);
      expect(styles.base.blockquote.color).toBe(colors.secondaryText);
    },
  );
});
