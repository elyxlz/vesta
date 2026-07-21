import type { Ref } from "react";

export const CHAT_COMPOSER_MAX_LINES = 7;

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
