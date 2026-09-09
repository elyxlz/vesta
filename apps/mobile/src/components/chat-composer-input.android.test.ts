import { expect, it, vi } from "vitest";
import { ChatComposerInput } from "./chat-composer-input.android";
import { CHAT_COMPOSER_CONTROL_HEIGHT } from "./chat-composer-input.types";

vi.mock("react", async (load) => ({
  ...(await load<typeof import("react")>()),
  useRef: () => ({ current: null }),
  useCallback: (callback: unknown) => callback,
  useImperativeHandle: vi.fn(),
}));
vi.mock("react-native", () => ({
  StyleSheet: { create: (styles: unknown) => styles },
}));
vi.mock("@expo/ui/jetpack-compose", () => ({
  Host: "Host",
  Box: "Box",
  Text: "Text",
  BasicTextField: Object.assign("BasicTextField", {
    DecorationBox: "DecorationBox",
    Placeholder: "Placeholder",
    InnerTextField: "InnerTextField",
  }),
  useNativeState: (value: string) => ({ get: () => value, set: vi.fn() }),
}));
vi.mock("@expo/ui/jetpack-compose/modifiers", () => ({
  fillMaxWidth: () => ({ type: "fillMaxWidth" }),
  defaultMinSize: (size: unknown) => ({ type: "defaultMinSize", size }),
  padding: (start: number, top: number, end: number, bottom: number) => ({
    type: "padding",
    start,
    top,
    end,
    bottom,
  }),
}));
vi.mock("@/components/chat-composer-input-lifecycle", () => ({
  useChatComposerLifecycle: () => ({}),
}));

it.each(["", "A draft", "A draft\nwith two lines"])(
  "centers placeholder and editable text together for %j without fixing the height",
  (value) => {
    const host = ChatComposerInput({
      value,
      placeholder: "Message nova",
      placeholderTextColor: "gray",
      selectionColor: "gold",
      textColor: "black",
      onChangeText: vi.fn(),
    });
    const field = host.props.children;
    const modifiers = field.props.modifiers;
    const inset = modifiers.find((m: { type: string }) => m.type === "padding");
    expect(inset.top).toBe(inset.bottom);
    expect(inset.top + field.props.textStyle.lineHeight + inset.bottom).toBe(
      CHAT_COMPOSER_CONTROL_HEIGHT,
    );
    expect(
      modifiers.find((m: { type: string }) => m.type === "defaultMinSize"),
    ).toEqual({
      type: "defaultMinSize",
      size: { minHeight: CHAT_COMPOSER_CONTROL_HEIGHT },
    });
    const box = field.props.children.props.children;
    expect(box.props.contentAlignment).toBe("centerStart");
    expect(box.props.children).toHaveLength(2);
    expect(host.props.matchContents).toEqual({ vertical: true });
    expect(field.props.maxLines).toBeGreaterThan(1);
  },
);
