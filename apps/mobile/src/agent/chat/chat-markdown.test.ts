import { describe, expect, it, vi } from "vitest";
import { darkColors, lightColors } from "@/theme/colors";
import { chatMarkdownStyleSet } from "./chat-markdown";

vi.mock("react-native", () => ({ StyleSheet: { hairlineWidth: 1 } }));

describe("chat markdown list layout", () => {
  it.each(["bullet_list_content", "ordered_list_content"] as const)(
    "sizes %s from its text so a bubble holding only a list item keeps the item's width",
    (content) => {
      const { base } = chatMarkdownStyleSet(lightColors);
      expect(base[content]).toEqual({
        flexGrow: 1,
        flexShrink: 1,
        flexBasis: "auto",
        minWidth: 0,
      });
    },
  );
});

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
