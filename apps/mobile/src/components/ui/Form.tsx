import type { ComponentProps, ReactNode } from "react";
import { Pressable, StyleSheet, Switch, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";
import { Text, TextInput } from "./Typography";

type IconName = ComponentProps<typeof Ionicons>["name"];

interface FieldProps extends ComponentProps<typeof TextInput> {
  label?: string;
  description?: string;
  error?: string;
  accessory?: ReactNode;
}

export function Field({
  label,
  description,
  error,
  accessory,
  ...inputProps
}: FieldProps) {
  const { colors } = usePreferences();
  return (
    <View style={styles.field}>
      {label ? (
        <Text style={[styles.label, { color: colors.text }]}>{label}</Text>
      ) : null}
      {description ? (
        <Text style={[styles.description, { color: colors.secondaryText }]}>
          {description}
        </Text>
      ) : null}
      <View style={styles.inputContainer}>
        <TextInput
          {...inputProps}
          placeholderTextColor={colors.tertiaryText}
          selectionColor={colors.accent}
          style={[
            styles.input,
            {
              backgroundColor: colors.input,
              borderColor: error ? colors.danger : colors.border,
              color: colors.text,
            },
            accessory ? styles.inputWithAccessory : null,
            inputProps.multiline ? styles.multiline : null,
            inputProps.style,
          ]}
        />
        {accessory ? (
          <View style={styles.inputAccessory}>{accessory}</View>
        ) : null}
      </View>
      {error ? (
        <Text
          accessibilityRole="alert"
          style={[styles.error, { color: colors.danger }]}
        >
          {error}
        </Text>
      ) : null}
    </View>
  );
}

interface SectionProps {
  title?: string;
  footer?: string;
  children: ReactNode;
}

export function FormSection({ title, footer, children }: SectionProps) {
  const { colors } = usePreferences();
  return (
    <View style={styles.section}>
      {title ? (
        <Text
          family="heading"
          style={[styles.sectionTitle, { color: colors.secondaryText }]}
        >
          {title}
        </Text>
      ) : null}
      <View
        style={[
          styles.sectionBody,
          { backgroundColor: colors.card, borderColor: colors.border },
        ]}
      >
        {children}
      </View>
      {footer ? (
        <Text style={[styles.footer, { color: colors.secondaryText }]}>
          {footer}
        </Text>
      ) : null}
    </View>
  );
}

interface RowProps {
  label: string;
  detail?: string;
  icon?: IconName;
  value?: string;
  onPress?: () => void;
  destructive?: boolean;
  destructiveIcon?: boolean;
  trailing?: ReactNode;
}

export function FormRow({
  label,
  detail,
  icon,
  value,
  onPress,
  destructive = false,
  destructiveIcon = false,
  trailing,
}: RowProps) {
  const { colors } = usePreferences();
  const content = (
    <View style={styles.row}>
      {icon ? (
        <View style={[styles.rowIcon, { backgroundColor: colors.accentSoft }]}>
          <Ionicons
            name={icon}
            size={18}
            color={destructive || destructiveIcon ? colors.danger : colors.accent}
          />
        </View>
      ) : null}
      <View style={styles.rowText}>
        <Text
          style={[
            styles.rowLabel,
            { color: destructive ? colors.danger : colors.text },
          ]}
        >
          {label}
        </Text>
        {detail ? (
          <Text style={[styles.rowDetail, { color: colors.secondaryText }]}>
            {detail}
          </Text>
        ) : null}
      </View>
      {value ? (
        <Text style={[styles.value, { color: colors.secondaryText }]}>
          {value}
        </Text>
      ) : null}
      {trailing ? <View style={styles.rowTrailing}>{trailing}</View> : null}
      {onPress ? (
        <Ionicons
          name="chevron-forward"
          size={17}
          color={colors.tertiaryText}
        />
      ) : null}
    </View>
  );
  return onPress ? (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => ({ opacity: pressed ? 0.55 : 1 })}
    >
      {content}
    </Pressable>
  ) : (
    content
  );
}

interface SwitchRowProps extends Omit<
  RowProps,
  "trailing" | "onPress" | "value"
> {
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
}

export function SwitchRow({
  value,
  onValueChange,
  disabled = false,
  ...rowProps
}: SwitchRowProps) {
  const { colors } = usePreferences();
  return (
    <FormRow
      {...rowProps}
      trailing={
        <Switch
          value={value}
          onValueChange={onValueChange}
          disabled={disabled}
          trackColor={{ false: colors.input, true: colors.accent }}
        />
      }
    />
  );
}

const styles = StyleSheet.create({
  field: { gap: 7 },
  label: { fontSize: 15, fontWeight: "700" },
  description: { fontSize: 13, lineHeight: 18 },
  input: {
    minHeight: 48,
    borderRadius: radii.control,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 14,
    fontSize: 16,
  },
  inputContainer: { position: "relative" },
  inputWithAccessory: { paddingRight: 52 },
  inputAccessory: {
    position: "absolute",
    top: 0,
    right: 4,
    bottom: 0,
    justifyContent: "center",
  },
  multiline: { minHeight: 120, paddingTop: 13, textAlignVertical: "top" },
  error: { fontSize: 13, fontWeight: "600" },
  section: { gap: 8 },
  sectionTitle: {
    fontSize: 15,
    lineHeight: 20,
    fontWeight: "500",
    letterSpacing: -0.2,
    paddingHorizontal: 16,
  },
  sectionBody: {
    borderRadius: radii.card,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    overflow: "hidden",
    paddingVertical: 4,
  },
  footer: { fontSize: 13, lineHeight: 18, paddingHorizontal: 16 },
  row: {
    minHeight: 54,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  rowIcon: {
    width: 32,
    height: 32,
    borderRadius: 9,
    alignItems: "center",
    justifyContent: "center",
  },
  rowText: { flex: 1, gap: 2 },
  rowTrailing: {
    alignSelf: "stretch",
    alignItems: "center",
    justifyContent: "center",
  },
  rowLabel: { fontSize: 16, fontWeight: "600" },
  rowDetail: { fontSize: 12, lineHeight: 16 },
  value: { fontSize: 15 },
});
