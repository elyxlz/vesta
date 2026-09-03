import { ActivityIndicator } from "react-native";
import type { LoadingSpinnerProps } from "@/components/loading-spinner.types";

export function LoadingSpinner({
  size = "small",
  color,
  style,
}: LoadingSpinnerProps) {
  return <ActivityIndicator size={size} color={color} style={style} />;
}
