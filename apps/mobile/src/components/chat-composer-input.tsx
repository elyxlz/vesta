import {
  useImperativeHandle,
  useRef,
  useState,
  type ComponentRef,
} from "react";
import { StyleSheet, TextInput } from "react-native";
import {
  type ChatComposerInputProps,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

const MIN_HEIGHT = 36;
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
    paddingTop: 7,
    paddingBottom: 7,
    fontFamily: fontNames.sans.native["400"],
    fontSize: 17,
    lineHeight: 22,
  },
});

export type { ChatComposerInputRef };
