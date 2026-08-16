import { StyleSheet } from "react-native";
import { AlertDialog, Host, Text, TextButton } from "@expo/ui/jetpack-compose";
import type { ConfirmDialogProps } from "@/components/confirm-dialog.types";
import { usePreferences } from "@/preferences/PreferencesProvider";

// A Material 3 confirmation dialog. The Compose dialog floats in its own
// window, so the zero-size Host never affects the caller's layout.
export function ConfirmDialog({
  visible,
  title,
  message,
  confirmLabel,
  destructive = false,
  onConfirm,
  onDismiss,
}: ConfirmDialogProps) {
  const preferences = usePreferences();
  if (!visible) return null;

  return (
    <Host
      colorScheme={preferences.dark ? "dark" : "light"}
      seedColor={preferences.colors.accent}
      style={styles.host}
    >
      <AlertDialog onDismissRequest={onDismiss}>
        <AlertDialog.Title>
          <Text>{title}</Text>
        </AlertDialog.Title>
        <AlertDialog.Text>
          <Text>{message}</Text>
        </AlertDialog.Text>
        <AlertDialog.ConfirmButton>
          <TextButton
            colors={
              destructive
                ? { contentColor: preferences.colors.danger }
                : undefined
            }
            onClick={onConfirm}
          >
            <Text>{confirmLabel}</Text>
          </TextButton>
        </AlertDialog.ConfirmButton>
        <AlertDialog.DismissButton>
          <TextButton onClick={onDismiss}>
            <Text>Cancel</Text>
          </TextButton>
        </AlertDialog.DismissButton>
      </AlertDialog>
    </Host>
  );
}

const styles = StyleSheet.create({
  host: { position: "absolute", width: 0, height: 0 },
});
