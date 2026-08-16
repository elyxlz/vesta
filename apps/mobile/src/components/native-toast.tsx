import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { StyleSheet, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import * as Haptics from "expo-haptics";
import Animated, { FadeInDown, FadeOutUp } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { FullWindowOverlay } from "react-native-screens";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { darkColors, lightColors, type AppColors } from "@/theme/colors";
import { radii } from "@/theme/layout";

const TOAST_DURATION_MS = 4_500;
const IS_IOS = process.env.EXPO_OS === "ios";

type ToastMessage = {
  id: number;
  message: string;
};

type ToastContextValue = {
  showError: (error: unknown, fallback?: string) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }) {
  const nextId = useRef(0);
  const [toast, setToast] = useState<ToastMessage | null>(null);

  const showError = useCallback((error: unknown, fallback?: string) => {
    const message =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : (fallback ?? "Something went wrong");
    const trimmedMessage = message.trim();
    if (!trimmedMessage) return;
    nextId.current += 1;
    setToast({ id: nextId.current, message: trimmedMessage });
    void Haptics.notificationAsync(
      Haptics.NotificationFeedbackType.Error,
    ).catch(() => undefined);
  }, []);

  const dismiss = useCallback((id: number) => {
    setToast((current) => (current?.id === id ? null : current));
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timeout = setTimeout(() => dismiss(toast.id), TOAST_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [dismiss, toast]);

  const value = useMemo(() => ({ showError }), [showError]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <NativeToast toast={toast} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  const value = use(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}

function NativeToast({ toast }: { toast: ToastMessage | null }) {
  const insets = useSafeAreaInsets();
  const { dark } = usePreferences();
  const colors = dark ? lightColors : darkColors;
  if (!toast) return null;

  const content = (
    <Animated.View
      key={toast.id}
      accessibilityLiveRegion="assertive"
      accessibilityRole="alert"
      entering={FadeInDown.duration(220)}
      exiting={FadeOutUp.duration(180)}
      pointerEvents="auto"
      style={[styles.positioner, { top: insets.top + 8 }]}
    >
      {isGlassEffectAPIAvailable() ? (
        <GlassView
          colorScheme={dark ? "light" : "dark"}
          tintColor={colors.elevated}
          style={[styles.toast, { backgroundColor: colors.elevated }]}
        >
          <ToastContent message={toast.message} colors={colors} />
        </GlassView>
      ) : (
        <View
          style={[
            styles.toast,
            styles.fallback,
            {
              backgroundColor: colors.elevated,
              borderColor: colors.border,
            },
          ]}
        >
          <ToastContent message={toast.message} colors={colors} />
        </View>
      )}
    </Animated.View>
  );
  const overlay = (
    <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
      {content}
    </View>
  );

  return IS_IOS ? <FullWindowOverlay>{overlay}</FullWindowOverlay> : overlay;
}

function ToastContent({
  message,
  colors,
}: {
  message: string;
  colors: AppColors;
}) {
  return (
    <>
      <View style={[styles.icon, { backgroundColor: colors.input }]}>
        <Ionicons name="alert-circle" size={17} color={colors.danger} />
      </View>
      <Text
        selectable
        style={[styles.message, { color: colors.secondaryText }]}
      >
        {message}
      </Text>
    </>
  );
}

const styles = StyleSheet.create({
  positioner: {
    position: "absolute",
    left: 16,
    right: 16,
    alignItems: "center",
  },
  toast: {
    alignSelf: "center",
    maxWidth: 420,
    minHeight: 44,
    borderRadius: radii.pill,
    borderCurve: "continuous",
    paddingHorizontal: 10,
    paddingVertical: 6,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    boxShadow: "0 6px 18px rgba(0, 0, 0, 0.16)",
    overflow: "hidden",
  },
  fallback: { borderWidth: StyleSheet.hairlineWidth },
  icon: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  message: { flexShrink: 1, fontSize: 13, lineHeight: 17 },
});
