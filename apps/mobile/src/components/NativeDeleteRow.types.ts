import type { ReactElement } from "react";
import type { StyleProp, ViewStyle } from "react-native";

export interface NativeDeleteRowProps {
  children: ReactElement;
  containerStyle: StyleProp<ViewStyle>;
  deleteAccessibilityLabel: string;
  dangerColor: string;
  disabled?: boolean;
  onDelete: () => void;
}
