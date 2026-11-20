import { memo, useEffect, useMemo, useRef, useState } from "react";
import {
  Pressable,
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type NativeSyntheticEvent,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  type SharedValue,
} from "react-native-reanimated";
import { Ionicons, MaterialCommunityIcons } from "@expo/vector-icons";
import { requireOptionalNativeModule } from "expo";
import { requireNativeViewManager } from "expo-modules-core";
import { MenuView } from "@expo/ui/community/menu";
import { SymbolView } from "expo-symbols";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import type { ReplyTarget } from "@/agent/message-actions";
import { ATTACH_ACTIONS, runAttachAction } from "@/agent/chat/attach-menu";
import { QuotedBlock } from "@/agent/chat/quoted-block";
import type { PickedAsset } from "@/attachments/pick";
import { CHAT_COMPOSER_CONTROL_HEIGHT } from "@/components/chat-composer-input.types";

// A bare glyph button hugs its icon; the slop keeps the tap target at the control height.
const IS_IOS = process.env.EXPO_OS === "ios";
const GLYPH_BUTTON_WIDTH = 26;
const GLYPH_HIT_SLOP = (CHAT_COMPOSER_CONTROL_HEIGHT - GLYPH_BUTTON_WIDTH) / 2;

// The reply preview rides the composer's top edge: the slot's height slides to the preview's measured
// height and back to zero, and the preview stays mounted through the exit so it slides out whole.
export function ReplySlot({
  target,
  height,
  onCancel,
  onHeight,
}: {
  target: ReplyTarget | null;
  height: SharedValue<number>;
  onCancel: () => void;
  onHeight: (height: number) => void;
}) {
  const [shown, setShown] = useState(target);
  if (target !== null && target !== shown) setShown(target);
  const measured = useSharedValue(0);
  useEffect(() => {
    onHeight(target ? measured.get() : 0);
  }, [target, measured, onHeight]);
  const onContentLayout = (event: LayoutChangeEvent) => {
    measured.set(event.nativeEvent.layout.height);
    if (target) onHeight(event.nativeEvent.layout.height);
  };
  const slotStyle = useAnimatedStyle(() => ({
    height: height.get(),
    opacity:
      measured.get() > 0 ? Math.min(height.get() / measured.get(), 1) : 0,
  }));
  return (
    <Animated.View style={[styles.replySlot, slotStyle]}>
      {shown ? (
        <View
          accessibilityElementsHidden={!target}
          importantForAccessibility={target ? "auto" : "no-hide-descendants"}
          pointerEvents={target ? "auto" : "none"}
          onLayout={onContentLayout}
          style={styles.replySlotContent}
        >
          <ReplyPreview target={shown} onCancel={onCancel} />
        </View>
      ) : null}
    </Animated.View>
  );
}

const ReplyPreview = memo(function ReplyPreview({
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

// The plus glyph inside the composer is a picture only. The touch belongs to
// AttachMenuTrigger, which sits over it outside the glass: a menu grows out of
// the glass that holds its trigger, and that would be the whole composer.
export function AttachGlyph({ disabled }: { disabled: boolean }) {
  const { colors } = usePreferences();
  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.glyphButton, { opacity: disabled ? 0.38 : 1 }]}
    >
      <Ionicons name="add" size={26} color={colors.text} />
    </View>
  );
}

interface NativeMenuButtonProps {
  actions: readonly { id: string; title: string; systemImage: string }[];
  anchorRect: { x: number; y: number; width: number; height: number };
  enabled: boolean;
  label: string;
  onAction: (event: NativeSyntheticEvent<{ id: string }>) => void;
  style: StyleProp<ViewStyle>;
}

// Optional, so a build without the native module opens the menu from the
// trigger itself.
const NativeMenuButton =
  IS_IOS && requireOptionalNativeModule("VestaMenuButton")
    ? requireNativeViewManager<NativeMenuButtonProps>(
        "VestaMenuButton",
        "VestaMenuButtonView",
      )
    : null;

const NATIVE_ATTACH_ACTIONS = ATTACH_ACTIONS.map((action) => ({
  id: action.id,
  title: action.title,
  systemImage: action.image,
}));

// The space between the composer's top edge and the menu above it.
const ATTACH_MENU_GAP = 8;
const ATTACH_ANCHOR_HEIGHT = CHAT_COMPOSER_CONTROL_HEIGHT;
const ATTACH_ANCHOR_SETTLE_MS = 200;

// The trigger sits at the bottom of a column as tall as the composer, so the
// column's own layout gives the distance up to the composer's top edge. The
// menu grows up out of an invisible anchor above that edge, clear of the
// glass. The composer resizes on every frame of a reply slide, and a render
// in the middle of that slide resets its animated values for a frame, so the
// height is stored only once the layout is still.
export function AttachMenuTrigger({
  disabled,
  onAssets,
  inset,
}: {
  disabled: boolean;
  onAssets: (assets: PickedAsset[]) => void;
  inset: number;
}) {
  const { dark } = usePreferences();
  const [rise, setRise] = useState(0);
  const settleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (settleTimer.current) clearTimeout(settleTimer.current);
    },
    [],
  );
  const onColumnLayout = (event: LayoutChangeEvent) => {
    const next = event.nativeEvent.layout.height - CHAT_COMPOSER_CONTROL_HEIGHT;
    if (settleTimer.current) clearTimeout(settleTimer.current);
    settleTimer.current = setTimeout(() => {
      settleTimer.current = null;
      setRise(next);
    }, ATTACH_ANCHOR_SETTLE_MS);
  };
  return (
    <View
      onLayout={onColumnLayout}
      pointerEvents="box-none"
      style={[styles.attachColumn, { left: inset, bottom: inset }]}
    >
      {NativeMenuButton ? (
        <NativeMenuButton
          actions={NATIVE_ATTACH_ACTIONS}
          anchorRect={{
            x: -inset,
            y: -rise - ATTACH_MENU_GAP - ATTACH_ANCHOR_HEIGHT,
            width: GLYPH_BUTTON_WIDTH,
            height: ATTACH_ANCHOR_HEIGHT,
          }}
          enabled={!disabled}
          label="Add attachment"
          onAction={({ nativeEvent }) =>
            runAttachAction(nativeEvent.id, onAssets)
          }
          style={styles.glyphButton}
        />
      ) : (
        <View pointerEvents={disabled ? "none" : "auto"}>
          <MenuView
            actions={[...ATTACH_ACTIONS]}
            colorScheme={dark ? "dark" : "light"}
            onPressAction={({ nativeEvent }) =>
              runAttachAction(nativeEvent.event, onAssets)
            }
          >
            <View
              accessible
              accessibilityLabel="Add attachment"
              accessibilityRole="button"
              accessibilityState={{ disabled }}
              hitSlop={GLYPH_HIT_SLOP}
              style={styles.glyphButton}
            />
          </MenuView>
        </View>
      )}
    </View>
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
  // Only the conversation button keeps a filled disc; the rest are bare glyphs whose color
  // carries the meaning.
  const filled = kind === "conversation";
  const glyphColor: Record<ActionKind, string> = {
    dictate: colors.text,
    confirm: colors.accent,
    cancel: colors.danger,
    conversation: colors.accentText,
    send: colors.text,
  };
  const icon: Record<ActionKind, keyof typeof Ionicons.glyphMap> = {
    dictate: "mic",
    confirm: "checkmark",
    cancel: "close",
    conversation: "pulse",
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
      hitSlop={filled ? 6 : GLYPH_HIT_SLOP}
      onPress={onPress}
      style={({ pressed }) => [
        filled ? styles.roundButton : styles.glyphButton,
        {
          backgroundColor: filled ? colors.accent : "transparent",
          opacity: disabled ? 0.38 : pressed ? 0.72 : 1,
        },
      ]}
    >
      {kind === "conversation" ? (
        IS_IOS ? (
          <SymbolView
            name="waveform"
            size={20}
            tintColor={glyphColor[kind]}
            resizeMode="scaleAspectFit"
          />
        ) : (
          <MaterialCommunityIcons
            name="waveform"
            size={22}
            color={glyphColor[kind]}
          />
        )
      ) : (
        <Ionicons name={icon[kind]} size={24} color={glyphColor[kind]} />
      )}
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
  replySlot: { overflow: "hidden" },
  replySlotContent: { position: "absolute", top: 0, right: 0, left: 0 },
  actionCluster: { flexDirection: "row", alignItems: "center", gap: 12 },
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
  attachColumn: {
    position: "absolute",
    top: 0,
    width: GLYPH_BUTTON_WIDTH,
    justifyContent: "flex-end",
  },
  glyphButton: {
    width: GLYPH_BUTTON_WIDTH,
    height: CHAT_COMPOSER_CONTROL_HEIGHT,
    alignItems: "center",
    justifyContent: "center",
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
