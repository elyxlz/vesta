import { useEffect, useImperativeHandle, useRef } from "react";
import { StyleSheet } from "react-native";
import {
  Host,
  Text,
  TextField,
  type TextFieldRef,
  useNativeState,
} from "@expo/ui/swift-ui";
import {
  font,
  foregroundStyle,
  frame,
  lineLimit,
  lineSpacing,
  padding,
  textFieldStyle,
  textInputAutocapitalization,
  tint,
} from "@expo/ui/swift-ui/modifiers";
import {
  CHAT_COMPOSER_MAX_LINES,
  type ChatComposerInputProps,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

const fontModifier = font({
  family: fontNames.sans.native["400"],
  size: 17,
});

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
  const nativeValue = useNativeState(value);
  const nativeRef = useRef<TextFieldRef>(null);

  useEffect(() => {
    if (nativeValue.get() !== value) nativeValue.set(value);
  }, [nativeValue, value]);

  useImperativeHandle(
    ref,
    () => ({
      focus: () => {
        void nativeRef.current?.focus();
      },
    }),
    [],
  );

  return (
    <Host
      ignoreSafeArea="all"
      matchContents={{ vertical: true }}
      style={styles.host}
    >
      <TextField
        ref={nativeRef}
        axis="vertical"
        maxLength={maxLength}
        onTextChange={onChangeText}
        placeholder={placeholder}
        text={nativeValue}
        modifiers={[
          fontModifier,
          lineSpacing(5),
          foregroundStyle(textColor),
          tint(selectionColor),
          textFieldStyle("plain"),
          textInputAutocapitalization("sentences"),
          lineLimit({ min: 1, max: CHAT_COMPOSER_MAX_LINES }),
          padding({ top: 8, bottom: 6, leading: 9, trailing: 4 }),
          frame({ minHeight: 36, maxHeight: 180, alignment: "topLeading" }),
        ]}
      >
        <TextField.Placeholder>
          <Text
            modifiers={[
              fontModifier,
              foregroundStyle(placeholderTextColor),
            ]}
          >
            {placeholder}
          </Text>
        </TextField.Placeholder>
      </TextField>
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { flex: 1 },
});

export type { ChatComposerInputRef };
