export interface OptionPickerOption<T extends string> {
  value: T;
  label: string;
}

export interface OptionPickerProps<T extends string> {
  visible: boolean;
  title: string;
  message?: string;
  options: readonly OptionPickerOption<T>[];
  selectedValue?: T;
  onSelect: (value: T) => void;
  onDismiss: () => void;
}
