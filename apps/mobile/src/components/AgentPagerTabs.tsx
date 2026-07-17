import { useMemo, type ReactNode } from "react";
import { Pressable, StyleSheet, View, type ViewStyle } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  GlassView,
  isGlassEffectAPIAvailable,
  type GlassEffectStyleConfig,
} from "expo-glass-effect";
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
const TAB_WIDTH = 52;
const TAB_HEIGHT = 40;
const SURFACE_HEIGHT = TAB_HEIGHT + BAR_PADDING * 2;

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
  visible: boolean;
  interactive: boolean;
  tabs: readonly AgentPagerTab[];
  onSelect: (page: number) => void;
}

function TabSurface({
  children,
  selectionStyle,
  visibility,
  visible,
  width,
}: {
  children: ReactNode;
  selectionStyle: AnimatedStyle<ViewStyle>;
  visibility: SharedValue<number>;
  visible: boolean;
  width: number;
}) {
  const { colors, dark } = usePreferences();
  const glassEffectStyle = useMemo<GlassEffectStyleConfig>(
    () => ({
      style: visible ? "regular" : "none",
      animate: true,
      animationDuration: 0.22,
    }),
    [visible],
  );
  const contentVisibilityStyle = useAnimatedStyle(() => ({
    opacity: visibility.value,
  }));
  const fallbackVisibilityStyle = useAnimatedStyle(() => ({
    opacity: visibility.value,
  }));

  const layers = (
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
        colorScheme={dark ? "dark" : "light"}
        glassEffectStyle={glassEffectStyle}
        isInteractive
        style={[styles.surface, { width }]}
      >
        <Animated.View
          style={[styles.surfaceContent, contentVisibilityStyle]}
        >
          {layers}
        </Animated.View>
      </GlassView>
    );
  }

  return (
    <Animated.View
      style={[
        styles.surface,
        styles.surfaceFallback,
        { width },
        { backgroundColor: colors.elevated, borderColor: colors.border },
        fallbackVisibilityStyle,
      ]}
    >
      {layers}
    </Animated.View>
  );
}

export function AgentPagerTabs({
  activePage,
  bottom,
  progress,
  visibility,
  visible,
  interactive,
  tabs,
  onSelect,
}: AgentPagerTabsProps) {
  const surfaceWidth = tabs.length * TAB_WIDTH + BAR_PADDING * 2;
  const overlayStyle = useAnimatedStyle(() => ({
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
      <TabSurface
        selectionStyle={selectionStyle}
        visibility={visibility}
        visible={visible}
        width={surfaceWidth}
      >
        {tabs.map((tab, index) => (
          <Tab
            key={tab.key}
            label={tab.label}
            icon={tab.icon}
            index={index}
            progress={progress}
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
  index,
  progress,
  selectedIcon,
  selected,
  onPress,
}: {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  index: number;
  progress: SharedValue<number>;
  selectedIcon: keyof typeof Ionicons.glyphMap;
  selected: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  const outlineStyle = useAnimatedStyle(() => ({
    opacity: interpolate(
      Math.abs(progress.value - index),
      [0, 1],
      [0, 1],
      Extrapolation.CLAMP,
    ),
    transform: [
      {
        scale: interpolate(
          Math.abs(progress.value - index),
          [0, 1],
          [0.84, 1],
          Extrapolation.CLAMP,
        ),
      },
    ],
  }));
  const filledStyle = useAnimatedStyle(() => {
    const distance = Math.abs(progress.value - index);
    return {
      opacity: interpolate(
        distance,
        [0, 1],
        [1, 0],
        Extrapolation.CLAMP,
      ),
      transform: [
        {
          scale: interpolate(
            distance,
            [0, 1],
            [1, 0.84],
            Extrapolation.CLAMP,
          ),
        },
      ],
    };
  });

  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityLabel={label}
      accessibilityState={{ selected }}
      onPress={onPress}
      style={styles.tab}
    >
      <View style={styles.iconSlot}>
        <Animated.View style={[styles.iconLayer, outlineStyle]}>
          <Ionicons name={icon} size={19} color={colors.secondaryText} />
        </Animated.View>
        <Animated.View style={[styles.iconLayer, filledStyle]}>
          <Ionicons name={selectedIcon} size={19} color={colors.text} />
        </Animated.View>
      </View>
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
    height: SURFACE_HEIGHT,
    borderRadius: radii.pill,
  },
  surfaceContent: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
  },
  surfaceFallback: { borderWidth: StyleSheet.hairlineWidth },
  selection: {
    position: "absolute",
    top: BAR_PADDING,
    left: BAR_PADDING,
    width: TAB_WIDTH,
    height: TAB_HEIGHT,
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
    height: TAB_HEIGHT,
    alignItems: "center",
    justifyContent: "center",
  },
  iconSlot: { width: 22, height: 22 },
  iconLayer: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: "center",
    justifyContent: "center",
  },
});
