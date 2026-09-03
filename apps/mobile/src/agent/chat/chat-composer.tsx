import { memo, useMemo } from "react";
import { Pressable, StyleSheet, View } from "react-native";
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

export function AttachButton({
  disabled,
  onPress,
}: {
  disabled: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  return (
    <Pressable
      accessibilityLabel="Add attachment"
      accessibilityRole="button"
      disabled={disabled}
      hitSlop={6}
      onPress={onPress}
      style={({ pressed }) => [
        styles.roundButton,
        {
          backgroundColor: colors.input,
          opacity: disabled ? 0.38 : pressed ? 0.72 : 1,
        },
      ]}
    >
      <Ionicons name="add" size={20} color={colors.text} />
    </Pressable>
  );
}

type ActionKind = "dictate" | "confirm" | "cancel" | "conversation" | "send";

function RoundAction({
  kind,
  disabled,
  onPress,
}: {
  kind: ActionKind;
  disabled: boolean;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  const primary = kind === "confirm" || kind === "conversation";
  const danger = kind === "cancel";
  const icon: Record<ActionKind, keyof typeof Ionicons.glyphMap> = {
    dictate: "mic",
    confirm: "checkmark",
    cancel: "close",
    conversation: "chatbubbles",
    send: "arrow-up",
  };
  const label: Record<ActionKind, string> = {
    dictate: "Dictate",
    confirm: "Send dictation",
    cancel: "Discard dictation",
    conversation: "Start voice conversation",
    send: "Send message",
  };
  return (
    <Pressable
      accessibilityLabel={label[kind]}
      accessibilityRole="button"
      disabled={disabled}
      hitSlop={6}
      onPress={onPress}
      style={({ pressed }) => [
        styles.roundButton,
        {
          backgroundColor: primary
            ? colors.accent
            : danger
              ? colors.danger
              : colors.input,
          opacity: disabled ? 0.38 : pressed ? 0.72 : 1,
        },
      ]}
    >
      <Ionicons
        name={icon[kind]}
        size={kind === "send" || kind === "confirm" ? 17 : 16}
        color={primary ? colors.accentText : danger ? "white" : colors.text}
      />
    </Pressable>
  );
}

// The composer's right cluster. Dictation swaps the row for discard and confirm; otherwise the
// mic dictates and the trailing slot sends a draft or opens a voice conversation.
export function ComposerActions({
  canSend,
  hasDraft,
  recordingMode,
  voiceEnabled,
  onSend,
  onDictate,
  onConfirm,
  onCancel,
  onConversation,
}: {
  canSend: boolean;
  hasDraft: boolean;
  recordingMode: "dictation" | "conversation" | null;
  voiceEnabled: boolean;
  onSend: () => void;
  onDictate: () => void;
  onConfirm: () => void;
  onCancel: () => void;
  onConversation: () => void;
}) {
  if (recordingMode === "dictation") {
    return (
      <View style={styles.actionCluster}>
        <RoundAction kind="cancel" disabled={false} onPress={onCancel} />
        <RoundAction kind="confirm" disabled={!canSend} onPress={onConfirm} />
      </View>
    );
  }
  if (!voiceEnabled) {
    return (
      <RoundAction
        kind="send"
        disabled={!canSend || !hasDraft}
        onPress={onSend}
      />
    );
  }
  return (
    <View style={styles.actionCluster}>
      <RoundAction kind="dictate" disabled={!canSend} onPress={onDictate} />
      {hasDraft ? (
        <RoundAction kind="send" disabled={!canSend} onPress={onSend} />
      ) : (
        <RoundAction
          kind="conversation"
          disabled={!canSend}
          onPress={onConversation}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  actionCluster: { flexDirection: "row", alignItems: "center", gap: 6 },
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
