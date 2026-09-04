import { useImperativeHandle, useRef, type ComponentRef } from "react";
import { StyleSheet, TextInput } from "react-native";
import {
  CHAT_COMPOSER_CONTROL_HEIGHT,
  type ChatComposerInputProps,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

const LINE_HEIGHT = 22;
const MIN_HEIGHT = CHAT_COMPOSER_CONTROL_HEIGHT;
const VERTICAL_PADDING = (MIN_HEIGHT - LINE_HEIGHT) / 2;
const MAX_HEIGHT = 180;

// No fixed height: the new-architecture text input measures its own text, so layout grows it
// between the min and max heights. A height pinned from state would freeze layout, and the
// content-size event only fires on a layout change.
export function ChatComposerInput({
  ref,
  value,
  placeholder,
  placeholderTextColor,
  selectionColor,
  textColor,
  maxLength,
  onChangeText,
}: ChatComposerInputProps) {
  const nativeRef = useRef<ComponentRef<typeof TextInput>>(null);

  useImperativeHandle(
    ref,
    () => ({ focus: () => nativeRef.current?.focus() }),
    [],
  );

  return (
    <TextInput
      ref={nativeRef}
      maxLength={maxLength}
      multiline
      onChangeText={onChangeText}
      placeholder={placeholder}
      placeholderTextColor={placeholderTextColor}
      selectionColor={selectionColor}
      style={[styles.input, { color: textColor }]}
      value={value}
    />
  );
}

const styles = StyleSheet.create({
  input: {
    flex: 1,
    minHeight: MIN_HEIGHT,
    maxHeight: MAX_HEIGHT,
    paddingHorizontal: 9,
    paddingTop: VERTICAL_PADDING,
    paddingBottom: VERTICAL_PADDING,
    fontFamily: fontNames.sans.native["400"],
    fontSize: 17,
    lineHeight: LINE_HEIGHT,
  },
});

export type { ChatComposerInputRef };
