import { useEffect, useRef } from "react";
import { Alert } from "react-native";
import type { ConfirmDialogProps } from "@/components/confirm-dialog.types";

// Bridges the declarative confirm API onto the imperative system alert: each
// visible=true transition presents exactly one alert, and exactly one of
// onConfirm or onDismiss fires per presentation.
export function ConfirmDialog({
  visible,
  title,
  message,
  confirmLabel,
  destructive = false,
  onConfirm,
  onDismiss,
}: ConfirmDialogProps) {
  const presented = useRef(false);

  useEffect(() => {
    if (!visible) {
      presented.current = false;
      return;
    }
    if (presented.current) return;
    presented.current = true;
    Alert.alert(title, message, [
      { text: "Cancel", style: "cancel", onPress: onDismiss },
      {
        text: confirmLabel,
        style: destructive ? "destructive" : "default",
        onPress: onConfirm,
      },
    ]);
  }, [
    visible,
    title,
    message,
    confirmLabel,
    destructive,
    onConfirm,
    onDismiss,
  ]);

  return null;
}
