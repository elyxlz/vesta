import type { ReactNode } from "react";
import { Pressable, StyleSheet, View, type ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  GlassView,
  isGlassEffectAPIAvailable,
  type GlassViewProps,
} from "expo-glass-effect";
import Animated, {
  Extrapolation,
  interpolate,
  useAnimatedProps,
  useAnimatedStyle,
  type AnimatedStyle,
  type SharedValue,
} from "react-native-reanimated";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { radii } from "@/theme/layout";

const BAR_WIDTH = 104;
const BAR_PADDING = 4;
const TAB_WIDTH = (BAR_WIDTH - BAR_PADDING * 2) / 2;
const AnimatedGlassView = Animated.createAnimatedComponent(GlassView);

interface AgentPagerTabsProps {
  activePage: number;
  top: number;
  progress: SharedValue<number>;
  interactive: boolean;
  onSelect: (page: number) => void;
}

function TabSurface({
  children,
  selectionStyle,
  glassAnimatedProps,
}: {
  children: ReactNode;
  selectionStyle: AnimatedStyle<ViewStyle>;
  glassAnimatedProps: Partial<GlassViewProps>;
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
      <AnimatedGlassView
        animatedProps={glassAnimatedProps}
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={styles.surface}
      >
        {content}
      </AnimatedGlassView>
    );
  }

  return (
    <View
      style={[
        styles.surface,
        styles.surfaceFallback,
        { backgroundColor: colors.elevated, borderColor: colors.border },
      ]}
    >
      {content}
    </View>
  );
}

export function AgentPagerTabs({
  activePage,
  top,
  progress,
  interactive,
  onSelect,
}: AgentPagerTabsProps) {
  const overlayStyle = useAnimatedStyle(() => {
    const visibility = interpolate(
      progress.value,
      [0, 0.16, 0.84, 1],
      [0, 1, 1, 0],
      Extrapolation.CLAMP,
    );
    return {
      opacity: visibility,
      transform: [
        {
          translateY: interpolate(
            visibility,
            [0, 1],
            [-10, 0],
            Extrapolation.CLAMP,
          ),
        },
      ],
    };
  });
  const selectionStyle = useAnimatedStyle(() => ({
    transform: [
      {
        translateX: interpolate(
          progress.value,
          [0, 0.16, 0.84, 1],
          [0, 0, TAB_WIDTH, TAB_WIDTH],
          Extrapolation.CLAMP,
        ),
      },
    ],
  }));
  const glassAnimatedProps = useAnimatedProps<GlassViewProps>(() => {
    const visibility = interpolate(
      progress.value,
      [0, 0.16, 0.84, 1],
      [0, 1, 1, 0],
      Extrapolation.CLAMP,
    );
    return {
      glassEffectStyle: visibility > 0.01 ? "regular" : "none",
    };
  });

  return (
    <Animated.View
      pointerEvents={interactive ? "box-none" : "none"}
      style={[styles.overlay, { top }, overlayStyle]}
    >
      <TabSurface
        selectionStyle={selectionStyle}
        glassAnimatedProps={glassAnimatedProps}
      >
        <Tab
          label="Chat"
          icon="chatbubble-outline"
          selectedIcon="chatbubble"
          selected={activePage === 0}
          onPress={() => onSelect(0)}
        />
        <Tab
          label="Dashboard"
          icon="grid-outline"
          selectedIcon="grid"
          selected={activePage === 1}
          onPress={() => onSelect(1)}
        />
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
    width: BAR_WIDTH,
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
