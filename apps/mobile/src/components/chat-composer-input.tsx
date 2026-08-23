import {
  useImperativeHandle,
  useRef,
  useState,
  type ComponentRef,
} from "react";
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
  const [height, setHeight] = useState(MIN_HEIGHT);

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
      onContentSizeChange={(event) =>
        setHeight(
          Math.min(
            Math.max(event.nativeEvent.contentSize.height, MIN_HEIGHT),
            MAX_HEIGHT,
          ),
        )
      }
      placeholder={placeholder}
      placeholderTextColor={placeholderTextColor}
      scrollEnabled={height >= MAX_HEIGHT}
      selectionColor={selectionColor}
      style={[styles.input, { color: textColor, height }]}
      value={value}
    />
  );
}

const styles = StyleSheet.create({
  input: {
    flex: 1,
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
