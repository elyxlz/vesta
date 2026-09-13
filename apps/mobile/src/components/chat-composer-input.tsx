import {
  useCallback,
  useDeferredValue,
  useImperativeHandle,
  useRef,
  useState,
  type ComponentRef,
} from "react";
import { StyleSheet, TextInput } from "react-native";
import {
  CHAT_COMPOSER_CONTROL_HEIGHT,
  CHAT_COMPOSER_INPUT_HORIZONTAL_PADDING,
  type ChatComposerInputProps,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input.types";
import { fontNames } from "@/theme/typography";

const LINE_HEIGHT = 22;
const MIN_HEIGHT = CHAT_COMPOSER_CONTROL_HEIGHT;
const VERTICAL_PADDING = (MIN_HEIGHT - LINE_HEIGHT) / 2;
const MAX_HEIGHT = 180;

// The new-architecture text input measures its own text, so layout grows it between the min
// and max heights. A typed value is committed by the native view first and measures right away.
// A value set from code (a send's clear, edit and resend, a dictation transcript) is measured one
// commit late: layout reads the previous text before the input's state takes the new one, and
// the native re-sync is skipped because the text already matches. So such a value is committed
// twice: first pinned to the height layout last gave the input, which is what the stale
// measurement would yield anyway, then released for a fresh measurement once the deferred
// value has caught up.
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
  const [typed, setTyped] = useState(value);
  const [laidOutHeight, setLaidOutHeight] = useState(MIN_HEIGHT);
  const settled = useDeferredValue(value);
  const pinned = value !== typed && value !== settled;
  const handleChangeText = useCallback(
    (text: string) => {
      setTyped(text);
      onChangeText(text);
    },
    [onChangeText],
  );

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
      onChangeText={handleChangeText}
      onLayout={(event) => {
        setLaidOutHeight(event.nativeEvent.layout.height);
      }}
      placeholder={placeholder}
      placeholderTextColor={placeholderTextColor}
      selectionColor={selectionColor}
      style={[
        styles.input,
        {
          color: textColor,
          height: pinned ? laidOutHeight : undefined,
        },
      ]}
      value={value}
    />
  );
}

const styles = StyleSheet.create({
  input: {
    flex: 1,
    minHeight: MIN_HEIGHT,
    maxHeight: MAX_HEIGHT,
    paddingHorizontal: CHAT_COMPOSER_INPUT_HORIZONTAL_PADDING,
    paddingTop: VERTICAL_PADDING,
    paddingBottom: VERTICAL_PADDING,
    fontFamily: fontNames.sans.native["400"],
    fontSize: 17,
    lineHeight: LINE_HEIGHT,
  },
});

export type { ChatComposerInputRef };
