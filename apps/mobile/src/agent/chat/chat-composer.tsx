import { memo, useEffect, useMemo } from "react";
import { Pressable, StyleSheet } from "react-native";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import { Ionicons } from "@expo/vector-icons";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import type { ReplyTarget } from "@/agent/message-actions";
import { QuotedBlock } from "@/agent/chat/quoted-block";
import { CHAT_COMPOSER_CONTROL_HEIGHT } from "@/components/chat-composer-input.types";

export const ReplyPreview = memo(function ReplyPreview({
  target,
  onCancel,
}: {
  target: ReplyTarget;
  onCancel: () => void;
}) {
  const { colors } = usePreferences();
  const preview = useMemo(
    () => target.text.trim().replace(/\s+/g, " "),
    [target.text],
  );

  return (
    <QuotedBlock
      trailing={
        <Pressable
          accessibilityLabel="Cancel reply"
          hitSlop={8}
          onPress={onCancel}
          style={styles.replyClose}
        >
          <Ionicons name="close" size={17} color={colors.secondaryText} />
        </Pressable>
      }
    >
      <Text
        numberOfLines={1}
        style={[styles.replyLabel, { color: colors.interactive }]}
      >
        Replying to {target.sender}
      </Text>
      <Text
        numberOfLines={2}
        style={[styles.replyText, { color: colors.secondaryText }]}
      >
        {preview}
      </Text>
    </QuotedBlock>
  );
});

export function ComposerActionButton({
  canSend,
  hasDraft,
  voiceActive,
  voiceEnabled,
  onSend,
  onToggleVoice,
}: {
  canSend: boolean;
  hasDraft: boolean;
  voiceActive: boolean;
  voiceEnabled: boolean;
  onSend: () => void;
  onToggleVoice: () => void;
}) {
  const { colors } = usePreferences();
  const sendMode = !voiceEnabled || (hasDraft && !voiceActive);
  const sendProgress = useSharedValue(sendMode ? 1 : 0);

  useEffect(() => {
    sendProgress.set(
      withTiming(sendMode ? 1 : 0, {
        duration: 180,
      }),
    );
  }, [sendMode, sendProgress]);

  const voiceStyle = useAnimatedStyle(() => ({
    opacity: 1 - sendProgress.value,
    transform: [{ scale: 1 - sendProgress.value * 0.2 }],
  }));
  const sendStyle = useAnimatedStyle(() => ({
    opacity: sendProgress.value,
    transform: [{ scale: 0.76 + sendProgress.value * 0.24 }],
  }));
  const sendSurfaceStyle = useAnimatedStyle(() => ({
    opacity: sendProgress.value,
  }));
  const actionDisabled = sendMode
    ? !canSend || !hasDraft
    : !voiceEnabled || !canSend;

  return (
    <Pressable
      accessibilityLabel={
        voiceActive
          ? "Stop listening"
          : sendMode
            ? "Send message"
            : "Start voice input"
      }
      accessibilityRole="button"
      disabled={actionDisabled}
      hitSlop={6}
      onPress={sendMode ? onSend : onToggleVoice}
      style={({ pressed }) => [
        styles.roundButton,
        {
          backgroundColor: voiceActive ? colors.danger : colors.input,
          opacity: actionDisabled ? 0.38 : pressed ? 0.72 : 1,
        },
      ]}
    >
      <Reanimated.View
        pointerEvents="none"
        style={[
          styles.composerActionSurface,
          { backgroundColor: colors.accent },
          sendSurfaceStyle,
        ]}
      />
      <Reanimated.View
        pointerEvents="none"
        style={[styles.composerActionGlyph, voiceStyle]}
      >
        <Ionicons
          name={voiceActive ? "stop" : "mic"}
          size={16}
          color={voiceActive ? "white" : colors.text}
        />
      </Reanimated.View>
      <Reanimated.View
        pointerEvents="none"
        style={[styles.composerActionGlyph, sendStyle]}
      >
        <Ionicons name="arrow-up" size={17} color={colors.accentText} />
      </Reanimated.View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  replyLabel: { fontSize: 12, fontWeight: "600" },
  replyText: { fontSize: 13, lineHeight: 17 },
  replyClose: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  roundButton: {
    width: CHAT_COMPOSER_CONTROL_HEIGHT,
    height: CHAT_COMPOSER_CONTROL_HEIGHT,
    borderRadius: CHAT_COMPOSER_CONTROL_HEIGHT / 2,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
  composerActionSurface: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    borderRadius: CHAT_COMPOSER_CONTROL_HEIGHT / 2,
  },
  composerActionGlyph: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    alignItems: "center",
    justifyContent: "center",
  },
});
