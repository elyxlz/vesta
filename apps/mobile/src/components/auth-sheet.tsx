import { useState, type ReactNode } from "react";
import {
  Animated,
  KeyboardAvoidingView,
  StyleSheet,
  View,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { GatewayCloseButton } from "@/components/GatewayCloseButton";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";

type AuthSheetMode = "plain" | "keyboard" | "scroll";

interface AuthSheetProps {
  children: ReactNode;
  mode?: AuthSheetMode;
  title?: string;
  onClose?: () => void;
  hasGrabber?: boolean;
  gap?: number;
}

export function AuthSheet({
  children,
  mode = "plain",
  title,
  onClose,
  hasGrabber = false,
  gap,
}: AuthSheetProps) {
  const { colors } = usePreferences();
  const [scrollY] = useState(() => new Animated.Value(0));
  const topPadding = hasGrabber ? 36 : 28;
  const contentStyle = [
    styles.content,
    title ? null : { paddingTop: topPadding },
    gap === undefined ? null : { gap },
  ];
  const header = title ? (
    <AuthSheetHeader
      title={title}
      onClose={onClose}
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
        stickyHeaderIndices={title ? [0] : undefined}
      >
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
        {content}
      </KeyboardAvoidingView>
    );
  }

  return content;
}

function AuthSheetHeader({
  title,
  onClose,
  topPadding,
  scrollY,
}: {
  title: string;
  onClose?: () => void;
  topPadding: number;
  scrollY?: Animated.Value;
}) {
  const { colors } = usePreferences();
  const headerContent = (
    <View style={styles.titleRow}>
      {onClose ? (
        <GatewayCloseButton
          color={colors.text}
          fallbackColor={colors.input}
          onPress={onClose}
        />
      ) : null}
      <Text family="heading" style={[styles.title, { color: colors.text }]}>
        {title}
      </Text>
    </View>
  );

  if (!scrollY) {
    return (
      <View style={{ paddingTop: topPadding }}>{headerContent}</View>
    );
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
    paddingBottom: 24,
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
    gap: 16,
  },
  title: {
    flex: 1,
    fontSize: 28,
    lineHeight: 34,
    fontWeight: "500",
    letterSpacing: -0.7,
  },
});
