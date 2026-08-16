import { useState, type ReactNode } from "react";
import { Animated, KeyboardAvoidingView, StyleSheet, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { useBottomInset } from "@/components/layout/use-bottom-inset";
import { SheetChrome } from "@/components/sheet-chrome";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

const IS_ANDROID = process.env.EXPO_OS === "android";
const BASE_BOTTOM_PADDING = 24;

type AuthSheetMode = "plain" | "keyboard" | "scroll";

interface AuthSheetProps {
  children: ReactNode;
  mode?: AuthSheetMode;
  title?: string;
  hasGrabber?: boolean;
  gap?: number;
}

export function AuthSheet({
  children,
  mode = "plain",
  title,
  hasGrabber = false,
  gap,
}: AuthSheetProps) {
  const { colors } = usePreferences();
  const bottomPadding = useBottomInset(BASE_BOTTOM_PADDING);
  const [scrollY] = useState(() => new Animated.Value(0));
  const topPadding = hasGrabber ? 36 : 28;
  // iOS floats a native grabber above the sheet; Android renders none, so
  // the Material drag handle renders in content there.
  const grabberChrome =
    hasGrabber && IS_ANDROID ? <SheetChrome grabber /> : null;
  const contentStyle = [
    styles.content,
    { paddingBottom: bottomPadding },
    title ? null : { paddingTop: topPadding },
    gap === undefined ? null : { gap },
  ];
  const header = title ? (
    <AuthSheetHeader
      title={title}
      topPadding={topPadding}
      scrollY={mode === "scroll" ? scrollY : undefined}
    />
  ) : null;

  if (mode === "scroll") {
    return (
      <Animated.ScrollView
        style={{ backgroundColor: colors.card }}
        contentContainerStyle={contentStyle}
        contentInsetAdjustmentBehavior="never"
        onScroll={Animated.event(
          [{ nativeEvent: { contentOffset: { y: scrollY } } }],
          { useNativeDriver: true },
        )}
        scrollEventThrottle={16}
        showsVerticalScrollIndicator={false}
        stickyHeaderIndices={title ? [grabberChrome ? 1 : 0] : undefined}
      >
        {grabberChrome}
        {header}
        {children}
      </Animated.ScrollView>
    );
  }

  const content = (
    <View
      style={[
        contentStyle,
        {
          backgroundColor: colors.card,
        },
      ]}
    >
      {header}
      {children}
    </View>
  );

  if (mode === "keyboard") {
    return (
      <KeyboardAvoidingView
        behavior={process.env.EXPO_OS === "ios" ? "padding" : undefined}
        style={{ backgroundColor: colors.card }}
      >
        {grabberChrome}
        {content}
      </KeyboardAvoidingView>
    );
  }

  if (grabberChrome) {
    return (
      <View style={{ backgroundColor: colors.card }}>
        {grabberChrome}
        {content}
      </View>
    );
  }

  return content;
}

function AuthSheetHeader({
  title,
  topPadding,
  scrollY,
}: {
  title: string;
  topPadding: number;
  scrollY?: Animated.Value;
}) {
  const { colors } = usePreferences();
  const headerContent = (
    <View style={styles.titleRow}>
      <Text family="heading" style={[styles.title, { color: colors.text }]}>
        {title}
      </Text>
    </View>
  );

  if (!scrollY) {
    return <View style={{ paddingTop: topPadding }}>{headerContent}</View>;
  }

  return (
    <View style={styles.stickyHeader}>
      <View
        style={[
          styles.scrollHeaderSurface,
          {
            backgroundColor: colors.card,
            paddingTop: topPadding,
          },
        ]}
      >
        {headerContent}
      </View>
      <Animated.View
        pointerEvents="none"
        style={[
          styles.scrollFade,
          {
            opacity: scrollY.interpolate({
              inputRange: [0, 10],
              outputRange: [0, 1],
              extrapolate: "clamp",
            }),
          },
        ]}
      >
        <LinearGradient
          colors={[colors.card, `${colors.card}00`]}
          style={StyleSheet.absoluteFill}
        />
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: 24,
  },
  stickyHeader: { marginHorizontal: -24 },
  scrollHeaderSurface: {
    paddingHorizontal: 24,
  },
  scrollFade: { height: 16 },
  titleRow: {
    minHeight: 38,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    flex: 1,
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "500",
    letterSpacing: -0.7,
    textAlign: "center",
  },
});
