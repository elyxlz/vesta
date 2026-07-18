import { ActivityIndicator, StyleSheet, View } from "react-native";
import { Button } from "./Button";
import { Text } from "./Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  const { colors } = usePreferences();
  return (
    <View style={styles.state}>
      <ActivityIndicator color={colors.accent} size="large" />
      <Text style={[styles.detail, { color: colors.secondaryText }]}>{label}</Text>
    </View>
  );
}

export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: { label: string; onPress: () => void };
}) {
  const { colors } = usePreferences();
  return (
    <View style={styles.state}>
      <Text family="heading" style={[styles.title, { color: colors.text }]}>{title}</Text>
      <Text style={[styles.detail, { color: colors.secondaryText }]}>{detail}</Text>
      {action ? <Button onPress={action.onPress}>{action.label}</Button> : null}
    </View>
  );
}

export function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <View style={styles.state}>
      <Text family="heading" style={[styles.title, { color: colors.danger }]}>Something went wrong</Text>
      <Text style={[styles.detail, { color: colors.secondaryText }]}>{message}</Text>
      {retry ? <Button onPress={retry}>Try again</Button> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  state: {
    flex: 1,
    minHeight: 240,
    justifyContent: "center",
    alignItems: "center",
    gap: 12,
    padding: 24,
  },
  title: { fontSize: 21, fontWeight: "500", textAlign: "center" },
  detail: { fontSize: 15, lineHeight: 21, textAlign: "center" },
});
