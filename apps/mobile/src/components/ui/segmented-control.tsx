import type { ComponentProps, ReactNode } from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

type IconName = ComponentProps<typeof Ionicons>["name"];

export interface SegmentedOption<Value extends string> {
  value: Value;
  label: string;
  icon?: IconName;
  /** Rendered above the label, for a visual sample of the option. */
  preview?: ReactNode;
}

export function SegmentedControl<Value extends string>({
  options,
  selectedValue,
  onSelect,
  accessibilityLabel,
}: {
  options: readonly SegmentedOption<Value>[];
  selectedValue: Value;
  onSelect: (value: Value) => void;
  accessibilityLabel: string;
}) {
  const { colors } = usePreferences();
  // With previews, the preview tile is the selectable surface and the
  // selection is a ring around it; without, the segment is a chip on a track.
  const tiled = options.some((option) => option.preview !== undefined);
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={[
        styles.track,
        tiled ? styles.tiledTrack : { backgroundColor: colors.input },
      ]}
    >
      {options.map((option) => {
        const selected = option.value === selectedValue;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            accessibilityLabel={option.label}
            onPress={() => {
              if (selected) return;
              void Haptics.selectionAsync();
              onSelect(option.value);
            }}
            style={({ pressed }) => [
              styles.segment,
              selected && !tiled
                ? { backgroundColor: colors.card, borderColor: colors.border }
                : null,
              { opacity: pressed && !selected ? 0.7 : 1 },
            ]}
          >
            {option.preview !== undefined ? (
              <View
                style={[
                  styles.tile,
                  {
                    borderColor: selected ? colors.accent : colors.border,
                    borderWidth: selected ? 2 : StyleSheet.hairlineWidth,
                  },
                ]}
              >
                {option.preview}
              </View>
            ) : null}
            {option.icon ? (
              <Ionicons
                name={option.icon}
                size={16}
                color={selected ? colors.text : colors.secondaryText}
              />
            ) : null}
            <Text
              style={[
                styles.label,
                { color: selected ? colors.accent : colors.secondaryText },
              ]}
            >
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  track: {
    flexDirection: "row",
    padding: 3,
    borderRadius: radii.card,
    borderCurve: "continuous",
  },
  tiledTrack: { padding: 0, gap: 10 },
  tile: {
    alignSelf: "stretch",
    padding: 2,
    borderRadius: 11,
    borderCurve: "continuous",
  },
  segment: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    minHeight: 38,
    borderRadius: radii.card - 3,
    borderCurve: "continuous",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "transparent",
  },
  label: { fontSize: 14, lineHeight: 18, fontWeight: "500" },
});
