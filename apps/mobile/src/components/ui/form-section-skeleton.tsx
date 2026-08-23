import { StyleSheet, View } from "react-native";
import { FormSection } from "@/components/ui/Form";
import { SkeletonPulse } from "@/components/ui/skeleton-pulse";
import { usePreferences } from "@/preferences/PreferencesProvider";

// Stands in for a settings card while its rows are fetched: the real section frame and title,
// with a label and value placeholder per row, so the page keeps its shape.
export function FormSectionSkeleton({
  title,
  rows,
  label,
}: {
  title?: string;
  rows: number;
  label: string;
}) {
  const { colors } = usePreferences();
  return (
    <SkeletonPulse label={label}>
      <FormSection title={title}>
        {Array.from({ length: rows }, (_, index) => (
          <View key={index} style={styles.row}>
            <View
              style={[
                styles.line,
                styles.rowLabel,
                { backgroundColor: colors.border },
              ]}
            />
            <View
              style={[
                styles.line,
                styles.rowValue,
                { backgroundColor: colors.border },
              ]}
            />
          </View>
        ))}
      </FormSection>
    </SkeletonPulse>
  );
}

const styles = StyleSheet.create({
  row: {
    minHeight: 44,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  line: { height: 12, borderRadius: 6 },
  rowLabel: { width: "38%" },
  rowValue: { width: "22%" },
});
