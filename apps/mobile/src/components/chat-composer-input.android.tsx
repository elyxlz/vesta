import { useEffect, useImperativeHandle, useRef } from "react";
import { StyleSheet } from "react-native";
import {
  BasicTextField,
  Box,
  Host,
  Text,
  type BasicTextFieldRef,
  useNativeState,
} from "@expo/ui/jetpack-compose";
import {
  defaultMinSize,
  fillMaxWidth,
  padding,
} from "@expo/ui/jetpack-compose/modifiers";
import {
  CHAT_COMPOSER_MAX_LINES,
  type ChatComposerInputProps,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

const textStyle = {
  fontFamily: fontNames.sans.native["400"],
  fontSize: 17,
  fontWeight: "400" as const,
  lineHeight: 22,
};

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
  const nativeRef = useRef<BasicTextFieldRef>(null);

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
      ignoreSafeAreaKeyboardInsets
      matchContents={{ vertical: true }}
      style={styles.host}
    >
      <BasicTextField
        ref={nativeRef}
        cursorColor={selectionColor}
        keyboardOptions={{ capitalization: "sentences" }}
        maxLength={maxLength}
        maxLines={CHAT_COMPOSER_MAX_LINES}
        minLines={1}
        modifiers={[
          fillMaxWidth(),
          defaultMinSize({ minHeight: 36 }),
          padding(9, 8, 4, 6),
        ]}
        onValueChange={onChangeText}
        textSelectionColors={{
          backgroundColor: selectionColor,
          handleColor: selectionColor,
        }}
        textStyle={{ ...textStyle, color: textColor }}
        value={nativeValue}
      >
        <BasicTextField.DecorationBox>
          <Box contentAlignment="topStart" modifiers={[fillMaxWidth()]}>
            <BasicTextField.Placeholder>
              <Text
                color={placeholderTextColor}
                modifiers={[fillMaxWidth()]}
                style={textStyle}
              >
                {placeholder}
              </Text>
            </BasicTextField.Placeholder>
            <BasicTextField.InnerTextField />
          </Box>
        </BasicTextField.DecorationBox>
      </BasicTextField>
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { flex: 1 },
});

export type { ChatComposerInputRef };
