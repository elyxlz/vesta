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

describe("chat markdown block layout", () => {
  it.each([
    "heading1",
    "heading2",
    "heading3",
    "heading4",
    "heading5",
    "heading6",
  ] as const)("lays %s out as a column so a long heading wraps", (heading) => {
    const { base } = chatMarkdownStyleSet(lightColors);
    expect(base[heading]).toMatchObject({
      flexDirection: "column",
      flexWrap: "nowrap",
    });
  });

  it.each(["th", "td"] as const)(
    "gives %s a minimum width so a bubble holding only a table has width",
    (cell) => {
      const { base } = chatMarkdownStyleSet(lightColors);
      expect(base[cell]).toMatchObject({ minWidth: 72 });
    },
  );

  it("gives an image a minimum width so a bubble holding only an image has height", () => {
    const { base } = chatMarkdownStyleSet(lightColors);
    expect(base.image).toMatchObject({ flex: 1, minWidth: 200 });
  });
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
