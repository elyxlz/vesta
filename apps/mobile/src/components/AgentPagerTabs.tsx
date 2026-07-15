import type { ReactNode } from "react";
import { Pressable, StyleSheet, View, type ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedStyle,
  type AnimatedStyle,
  type SharedValue,
} from "react-native-reanimated";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const BAR_PADDING = 4;
const TAB_WIDTH = 48;

export interface AgentPagerTab {
  key: string;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  selectedIcon: keyof typeof Ionicons.glyphMap;
}

interface AgentPagerTabsProps {
  activePage: number;
  bottom: number;
  progress: SharedValue<number>;
  visibility: SharedValue<number>;
  interactive: boolean;
  tabs: readonly AgentPagerTab[];
  onSelect: (page: number) => void;
}

function TabSurface({
  children,
  selectionStyle,
  width,
}: {
  children: ReactNode;
  selectionStyle: AnimatedStyle<ViewStyle>;
  width: number;
}) {
  const { colors, dark } = usePreferences();

  const content = (
    <>
      <Animated.View
        pointerEvents="none"
        style={[
          styles.selection,
          {
            backgroundColor: colors.accentSoft,
          },
          selectionStyle,
        ]}
      />
      <View style={styles.tabs}>{children}</View>
    </>
  );

  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={[styles.surface, { width }]}
      >
        {content}
      </GlassView>
    );
  }

  return (
    <View
      style={[
        styles.surface,
        styles.surfaceFallback,
        { width },
        { backgroundColor: colors.elevated, borderColor: colors.border },
      ]}
    >
      {content}
    </View>
  );
}

export function AgentPagerTabs({
  activePage,
  bottom,
  progress,
  visibility,
  interactive,
  tabs,
  onSelect,
}: AgentPagerTabsProps) {
  const surfaceWidth = tabs.length * TAB_WIDTH + BAR_PADDING * 2;
  const overlayStyle = useAnimatedStyle(() => ({
    opacity: visibility.value,
    transform: [
      {
        translateY: interpolate(
          visibility.value,
          [0, 1],
          [6, 0],
          Extrapolation.CLAMP,
        ),
      },
    ],
  }));
  const selectionStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          progress.value,
          [0, tabs.length - 1],
          [0, (tabs.length - 1) * TAB_WIDTH],
          Extrapolation.CLAMP,
        ),
      },
    ],
  }));
  return (
    <Animated.View
      pointerEvents={interactive ? "box-none" : "none"}
      accessibilityElementsHidden={!interactive}
      importantForAccessibility={interactive ? "auto" : "no-hide-descendants"}
      style={[styles.overlay, { bottom }, overlayStyle]}
    >
      <TabSurface selectionStyle={selectionStyle} width={surfaceWidth}>
        {tabs.map((tab, index) => (
          <Tab
            key={tab.key}
            label={tab.label}
            icon={tab.icon}
            selectedIcon={tab.selectedIcon}
            selected={activePage === index}
            onPress={() => onSelect(index)}
          />
        ))}
      </TabSurface>
    </Animated.View>
  );
}

function Tab({
  label,
  icon,
  selectedIcon,
  selected,
  onPress,
}: {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  selectedIcon: keyof typeof Ionicons.glyphMap;
  selected: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  const color = selected ? colors.text : colors.secondaryText;

  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityLabel={label}
      accessibilityState={{ selected }}
      onPress={onPress}
      style={styles.tab}
    >
      <Ionicons name={selected ? selectedIcon : icon} size={18} color={color} />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  overlay: {
    position: "absolute",
    zIndex: 10,
    left: 0,
    right: 0,
    alignItems: "center",
  },
  surface: {
    height: 44,
    borderRadius: radii.pill,
  },
  surfaceFallback: { borderWidth: StyleSheet.hairlineWidth },
  selection: {
    position: "absolute",
    top: BAR_PADDING,
    left: BAR_PADDING,
    width: TAB_WIDTH,
    height: 36,
    borderRadius: radii.pill,
  },
  tabs: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    padding: BAR_PADDING,
    flexDirection: "row",
  },
  tab: {
    width: TAB_WIDTH,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
  },
});
