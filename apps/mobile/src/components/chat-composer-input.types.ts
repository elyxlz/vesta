import type { Ref } from "react";

export const CHAT_COMPOSER_MAX_LINES = 7;
// Height of the single-line input and of the action button, so the collapsed
// row is one control tall with its text centered.
export const CHAT_COMPOSER_CONTROL_HEIGHT = 30;

export interface ChatComposerInputRef {
  focus: () => void;
}

export interface ChatComposerInputProps {
  ref?: Ref<ChatComposerInputRef>;
  value: string;
  placeholder: string;
  placeholderTextColor: string;
  selectionColor: string;
  textColor: string;
  maxLength?: number;
  onChangeText: (value: string) => void;
}
