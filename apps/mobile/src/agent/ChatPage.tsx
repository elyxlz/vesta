import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ActivityIndicator,
  Alert,
  Animated,
  Easing,
  FlatList,
  Linking,
  Pressable,
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type ListRenderItem,
} from "react-native";
import { useQuery } from "@tanstack/react-query";
import {
  KeyboardStickyView,
} from "react-native-keyboard-controller";
import Reanimated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import Markdown, {
  type ASTNode,
  type RenderRules,
} from "react-native-markdown-display";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import * as Clipboard from "expo-clipboard";
import * as Haptics from "expo-haptics";
import * as WebBrowser from "expo-web-browser";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";
import type { VestaEvent } from "@/api/types";
import { fetchVoiceStatus } from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import {
  ChatComposerInput,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input";
import { ChatLoadingSkeleton } from "@/components/chat-loading-skeleton";
import { Text } from "@/components/ui/Typography";
import {
  MessageContextMenu,
  type MessageMenuAction,
} from "@/components/message-context-menu";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { shareVestaMessage } from "@/sharing/share-message";
import { fontNames } from "@/theme/typography";
import { radii } from "@/theme/layout";
import { triggerTranscriptHaptic } from "@/voice/recording-haptics";
import { useLiveVoice, useSpeechPlayer } from "@/voice/useLiveVoice";
import {
  createInvertedChatRows,
  type ChatRow,
} from "@/agent/chat-list-model";
import {
  messageActionIds,
  quotedReply,
  type MessageActionId,
} from "@/agent/message-actions";
import { useInvertedChatScroll } from "@/agent/use-inverted-chat-scroll";

const USES_NATIVE_BUBBLE_SHAPE = process.env.EXPO_OS === "ios";
const COMPOSER_RESIZE_DURATION = 250;
const COMPOSER_SURFACE_PADDING = 4;
const CHAT_COMPOSER_GAP = 6;
const TRANSCRIPT_HAPTIC_INTERVAL_MS = 110;

const MESSAGE_ACTIONS: Record<MessageActionId, MessageMenuAction> = {
  reply: {
    id: "reply",
    title: "Reply",
    systemImage: "arrowshape.turn.up.left",
  },
  copy: { id: "copy", title: "Copy", systemImage: "doc.on.doc" },
  "edit-resend": {
    id: "edit-resend",
    title: "Edit & Resend",
    systemImage: "pencil",
  },
  "read-aloud": {
    id: "read-aloud",
    title: "Read Aloud",
    systemImage: "speaker.wave.2",
  },
  share: {
    id: "share",
    title: "Share",
    systemImage: "square.and.arrow.up",
  },
};

type ReplyTarget = { text: string; sender: string };

function isFinalMarkdownNode(
  node: ASTNode,
  parentNodes: ASTNode[],
): boolean {
  let child = node;
  for (const parent of parentNodes) {
    if (parent.children[parent.children.length - 1]?.key !== child.key) {
      return false;
    }
    child = parent;
  }
  return parentNodes[parentNodes.length - 1]?.type === "body";
}

function openMarkdownLink(href: string): boolean {
  const trimmedHref = href.trim();
  const target = /^[a-z][a-z\d+.-]*:/i.test(trimmedHref)
    ? trimmedHref
    : `https://${trimmedHref.replace(/^\/+/, "")}`;

  const open = /^https?:/i.test(target)
    ? WebBrowser.openBrowserAsync(target)
    : /^(mailto|tel|sms):/i.test(target)
      ? Linking.openURL(target)
      : Promise.reject(new Error("Unsupported link type"));

  void open.catch(() => {
    Alert.alert("Couldn’t open link", target);
  });
  return false;
}

function BubbleTail({
  user,
  fill,
  stroke,
}: {
  user: boolean;
  fill: string;
  stroke: string;
}) {
  const fillPath = user
    ? "M 0 16 L 20 2 C 20 11 21 14 25 15 H 26 C 20 16 17 14 15 12 C 11 15 5 16 0 16 Z"
    : "M 26 16 L 6 1 C 6 10 5 14 1 15 H 0 C 6 16 9 14 12 12 C 16 15 21 16 26 16 Z";

  return (
    <Svg
      pointerEvents="none"
      width={26}
      height={16}
      viewBox="0 0 26 16"
      style={[
        styles.bubbleTail,
        user ? styles.userBubbleTail : styles.agentBubbleTail,
      ]}
    >
      <Path d={fillPath} fill={fill} />
      {!user ? (
        <Path
          d="M 6 1 C 6 10 5 14 1 15 H 0 C 6 16 9 14 12 12"
          fill="none"
          stroke={stroke}
          strokeWidth={StyleSheet.hairlineWidth}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      ) : null}
    </Svg>
  );
}

function isSameCalendarDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function chatDateLabel(timestamp: string): string {
  const date = new Date(timestamp);
  const today = new Date();
  if (isSameCalendarDay(date, today)) return "Today";

  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  if (isSameCalendarDay(date, yesterday)) return "Yesterday";

  return date.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: date.getFullYear() === today.getFullYear() ? undefined : "numeric",
  });
}

const ChatDateHeader = memo(function ChatDateHeader({
  timestamp,
}: {
  timestamp: string;
}) {
  const { colors } = usePreferences();
  return (
    <View style={styles.dateHeader}>
      <Text
        accessibilityRole="header"
        style={[styles.dateHeaderText, { color: colors.tertiaryText }]}
      >
        {chatDateLabel(timestamp)}
      </Text>
    </View>
  );
});

const ChatEvent = memo(function ChatEvent({
  event,
  startsNewBubbleGroup,
  endsBubbleGroup,
  canSpeak,
  onReply,
  onEditAndResend,
  onReadAloud,
}: {
  event: VestaEvent;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
  canSpeak: boolean;
  onReply: (text: string, user: boolean) => void;
  onEditAndResend: (text: string) => void;
  onReadAloud: (text: string) => void;
}) {
  const { colors } = usePreferences();
  const timestamp = event.ts
    ? new Date(event.ts).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
      })
    : null;
  const markdownRules = useMemo<RenderRules>(
    () => ({
      textgroup: (node, children, parentNodes, markdownStyles) => (
        <Text key={node.key} style={markdownStyles.textgroup}>
          {children}
          {timestamp && isFinalMarkdownNode(node, parentNodes) ? (
            <Text
              key="timestamp-spacer"
              style={styles.timestampSpacer}
            >
              {"\u00A0\u00A0\u00A0\u00A0"}
              {timestamp}
            </Text>
          ) : null}
        </Text>
      ),
      paragraph: (node, children, parentNodes, markdownStyles) => (
        <View
          key={node.key}
          style={[
            markdownStyles._VIEW_SAFE_paragraph,
            parentNodes.some((parent) => parent.type === "blockquote")
              ? styles.markdownBlockquoteParagraph
              : null,
            isFinalMarkdownNode(node, parentNodes)
              ? styles.finalMarkdownParagraph
              : null,
          ]}
        >
          {children}
        </View>
      ),
      blockquote: (node, children) => (
        <View
          key={node.key}
          style={[
            styles.replyPreview,
            styles.markdownBlockquote,
            { backgroundColor: colors.input },
          ]}
        >
          <View
            style={[
              styles.replyAccent,
              { backgroundColor: colors.interactive },
            ]}
          />
          <View style={styles.replyCopy}>{children}</View>
        </View>
      ),
    }),
    [colors.input, colors.interactive, timestamp],
  );
  const markdownStyles = useMemo(
    () => ({
      body: {
        color: colors.text,
        fontFamily: fontNames.sans.native["400"],
        fontSize: 16,
        lineHeight: 23,
      },
      heading1: {
        color: colors.text,
        fontFamily: fontNames.heading.native["600"],
        fontSize: 22,
        lineHeight: 27,
        marginTop: 5,
        marginBottom: 8,
      },
      heading2: {
        color: colors.text,
        fontFamily: fontNames.heading.native["600"],
        fontSize: 20,
        lineHeight: 25,
        marginTop: 5,
        marginBottom: 7,
      },
      heading3: {
        color: colors.text,
        fontFamily: fontNames.heading.native["600"],
        fontSize: 18,
        lineHeight: 23,
        marginTop: 4,
        marginBottom: 6,
      },
      heading4: {
        color: colors.text,
        fontFamily: fontNames.sans.native["600"],
        fontSize: 16,
        lineHeight: 22,
        marginTop: 3,
        marginBottom: 5,
      },
      heading5: {
        color: colors.secondaryText,
        fontFamily: fontNames.sans.native["600"],
        fontSize: 15,
        lineHeight: 21,
        marginTop: 3,
        marginBottom: 4,
      },
      heading6: {
        color: colors.secondaryText,
        fontFamily: fontNames.sans.native["600"],
        fontSize: 13,
        lineHeight: 18,
        marginTop: 3,
        marginBottom: 4,
        textTransform: "uppercase" as const,
        letterSpacing: 0.4,
      },
      strong: { fontFamily: fontNames.sans.native["600"] },
      em: { fontStyle: "italic" as const },
      s: {
        color: colors.tertiaryText,
        textDecorationLine: "line-through" as const,
      },
      paragraph: { marginTop: 0, marginBottom: 8 },
      link: {
        color: colors.interactive,
        fontFamily: fontNames.sans.native["500"],
        textDecorationLine: "underline" as const,
        textDecorationColor: colors.interactive,
      },
      blocklink: { borderBottomWidth: 0 },
      blockquote: {
        color: colors.secondaryText,
        fontFamily: fontNames.sans.native["400"],
        fontSize: 13,
        lineHeight: 17,
      },
      bullet_list: { marginTop: 1, marginBottom: 7 },
      ordered_list: { marginTop: 1, marginBottom: 7 },
      list_item: { marginBottom: 3 },
      bullet_list_icon: {
        color: colors.secondaryText,
        width: 16,
        marginLeft: 1,
        marginRight: 4,
        fontSize: 17,
        lineHeight: 23,
      },
      ordered_list_icon: {
        color: colors.secondaryText,
        minWidth: 20,
        marginLeft: 0,
        marginRight: 5,
        fontFamily: fontNames.sans.native["500"],
        fontSize: 14,
        lineHeight: 23,
        textAlign: "right" as const,
        fontVariant: ["tabular-nums"] as const,
      },
      bullet_list_content: { flex: 1 },
      ordered_list_content: { flex: 1 },
      code_inline: {
        color: colors.text,
        fontFamily: fontNames.mono.native["400"],
        fontSize: 14,
        lineHeight: 20,
        backgroundColor: colors.code,
        borderWidth: 0,
        borderRadius: 5,
        paddingHorizontal: 4,
        paddingVertical: 1,
      },
      code_block: {
        color: colors.text,
        fontFamily: fontNames.mono.native["400"],
        fontSize: 13,
        lineHeight: 19,
        backgroundColor: colors.code,
        borderColor: colors.border,
        borderWidth: StyleSheet.hairlineWidth,
        borderRadius: 11,
        borderCurve: "continuous" as const,
        marginVertical: 6,
        padding: 10,
      },
      fence: {
        color: colors.text,
        fontFamily: fontNames.mono.native["400"],
        fontSize: 13,
        lineHeight: 19,
        backgroundColor: colors.code,
        borderColor: colors.border,
        borderWidth: StyleSheet.hairlineWidth,
        borderRadius: 11,
        borderCurve: "continuous" as const,
        marginVertical: 6,
        padding: 10,
      },
      hr: {
        height: StyleSheet.hairlineWidth,
        backgroundColor: colors.border,
        marginVertical: 11,
      },
      table: {
        borderColor: colors.border,
        borderWidth: StyleSheet.hairlineWidth,
        borderRadius: 9,
        borderCurve: "continuous" as const,
        marginVertical: 7,
        overflow: "hidden" as const,
      },
      thead: { backgroundColor: colors.input },
      tr: {
        borderBottomColor: colors.border,
        borderBottomWidth: StyleSheet.hairlineWidth,
      },
      th: { paddingHorizontal: 7, paddingVertical: 6 },
      td: { paddingHorizontal: 7, paddingVertical: 6 },
      image: {
        flex: 1,
        borderRadius: 11,
        borderCurve: "continuous" as const,
        marginVertical: 6,
        overflow: "hidden" as const,
      },
    }),
    [colors],
  );
  const user = event.type === "user";
  const messageText = "text" in event ? event.text : "";
  const actions = useMemo<MessageMenuAction[]>(
    () =>
      messageActionIds({ user, canSpeak }).map(
        (action) => MESSAGE_ACTIONS[action],
      ),
    [canSpeak, user],
  );
  const performAction = useCallback(
    (action: MessageActionId) => {
      switch (action) {
        case "reply":
          onReply(messageText, user);
          break;
        case "copy":
          void Clipboard.setStringAsync(messageText);
          break;
        case "edit-resend":
          onEditAndResend(messageText);
          break;
        case "read-aloud":
          onReadAloud(messageText);
          break;
        case "share":
          setTimeout(() => {
            void shareVestaMessage(messageText).catch(() => undefined);
          }, 250);
          break;
      }
    },
    [messageText, onEditAndResend, onReadAloud, onReply, user],
  );
  if (event.type === "error" || event.type === "rate_limited") {
    const text = event.type === "rate_limited" ? "Rate limited. Vesta will be back soon." : "This message may not have gone through.";
    return <Text style={[styles.systemMessage, { color: colors.tertiaryText }]}>{text}</Text>;
  }
  if (event.type === "tool_start") {
    return (
      <View
        style={[
          styles.messageRow,
          startsNewBubbleGroup ? styles.newBubbleGroup : null,
          styles.agentRow,
        ]}
      >
        <View style={[styles.tool, { backgroundColor: colors.input }]}>
          <Ionicons
            name="hammer-outline"
            size={11}
            color={colors.secondaryText}
          />
          <Text
            family="mono"
            numberOfLines={1}
            style={[styles.toolText, { color: colors.secondaryText }]}
          >
            {event.tool}: {event.input}
          </Text>
        </View>
      </View>
    );
  }
  if (event.type !== "user" && event.type !== "chat") return null;
  const bubbleColor = user ? colors.accent : colors.card;
  const bubble = (
    <View
      accessibilityHint="Long press for message actions"
      style={[
        styles.bubble,
        USES_NATIVE_BUBBLE_SHAPE
          ? null
          : [
              styles.bubbleFallback,
              { backgroundColor: bubbleColor },
              user
                ? null
                : {
                    borderColor: colors.border,
                    borderWidth: StyleSheet.hairlineWidth,
                  },
            ],
      ]}
    >
      {endsBubbleGroup && !USES_NATIVE_BUBBLE_SHAPE ? (
        <BubbleTail user={user} fill={bubbleColor} stroke={colors.border} />
      ) : null}
      {user ? (
        <Text style={[styles.userText, { color: colors.accentText }]}>
          {event.text}
          {timestamp ? (
            <Text style={styles.timestampSpacer}>
              {"\u00A0\u00A0\u00A0\u00A0"}
              {timestamp}
            </Text>
          ) : null}
        </Text>
      ) : (
        <Markdown
          onLinkPress={openMarkdownLink}
          rules={markdownRules}
          style={markdownStyles}
        >
          {event.text}
        </Markdown>
      )}
      {timestamp ? (
        <Text
          style={[
            styles.bubbleTimestamp,
            {
              color: user ? colors.accentText : colors.tertiaryText,
              opacity: user ? 0.58 : 1,
            },
          ]}
        >
          {timestamp}
        </Text>
      ) : null}
    </View>
  );
  return (
    <View
      style={[
        styles.messageRow,
        startsNewBubbleGroup ? styles.newBubbleGroup : null,
        user ? styles.userRow : styles.agentRow,
      ]}
    >
      <MessageContextMenu
        actions={actions}
        bubbleFillColor={bubbleColor}
        bubbleStrokeColor={user ? "transparent" : colors.border}
        bubbleStrokeWidth={user ? 0 : StyleSheet.hairlineWidth}
        onAction={(id) => performAction(id as MessageActionId)}
        previewCornerRadius={radii.bubble}
        style={styles.bubbleMenu}
        tailOverhang={endsBubbleGroup ? (user ? 5 : 6) : 0}
        tailSide={
          endsBubbleGroup ? (user ? "trailing" : "leading") : "none"
        }
      >
        {bubble}
      </MessageContextMenu>
    </View>
  );
});

const TypingIndicator = memo(function TypingIndicator({
  agentName,
  startsNewBubbleGroup,
}: {
  agentName: string;
  startsNewBubbleGroup: boolean;
}) {
  const { colors } = usePreferences();
  const [dots] = useState(() => [
    new Animated.Value(0),
    new Animated.Value(0),
    new Animated.Value(0),
  ]);

  useEffect(() => {
    const animations = dots.map((dot, index) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(index * 150),
          Animated.timing(dot, {
            toValue: 1,
            duration: 200,
            easing: Easing.out(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.timing(dot, {
            toValue: 0,
            duration: 200,
            easing: Easing.in(Easing.quad),
            useNativeDriver: true,
          }),
          Animated.delay(600 - index * 150),
        ]),
      ),
    );
    for (const animation of animations) animation.start();
    return () => {
      for (const animation of animations) animation.stop();
    };
  }, [dots]);

  return (
    <View
      accessible
      accessibilityLabel={`${agentName} is typing`}
      style={[
        styles.messageRow,
        startsNewBubbleGroup ? styles.newBubbleGroup : null,
        styles.agentRow,
      ]}
    >
      <View
        style={[
          styles.typingBubble,
          {
            backgroundColor: colors.card,
            borderColor: colors.border,
            borderWidth: StyleSheet.hairlineWidth,
          },
        ]}
      >
        <BubbleTail user={false} fill={colors.card} stroke={colors.border} />
        <View style={styles.typingDots}>
          {dots.map((dot, index) => (
            <Animated.View
              key={index}
              style={[
                styles.typingDot,
                {
                  backgroundColor: colors.secondaryText,
                  opacity: dot.interpolate({
                    inputRange: [0, 1],
                    outputRange: [0.35, 0.8],
                  }),
                  transform: [
                    {
                      translateY: dot.interpolate({
                        inputRange: [0, 1],
                        outputRange: [0, -3],
                      }),
                    },
                  ],
                },
              ]}
            />
          ))}
        </View>
      </View>
    </View>
  );
});

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
    <View
      style={[
        styles.replyPreview,
        { backgroundColor: colors.input },
      ]}
    >
      <View
        style={[
          styles.replyAccent,
          { backgroundColor: colors.interactive },
        ]}
      />
      <View style={styles.replyCopy}>
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
      </View>
      <Pressable
        accessibilityLabel="Cancel reply"
        hitSlop={8}
        onPress={onCancel}
        style={styles.replyClose}
      >
        <Ionicons name="close" size={17} color={colors.secondaryText} />
      </Pressable>
    </View>
  );
});

function ComposerSurface({ children }: { children: ReactNode }) {
  const { colors, dark } = usePreferences();
  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={styles.composerSurface}
      >
        {children}
      </GlassView>
    );
  }
  return (
    <View
      style={[
        styles.composerSurface,
        styles.composerFallback,
        { backgroundColor: colors.elevated, borderColor: colors.border },
      ]}
    >
      {children}
    </View>
  );
}

function ComposerActionButton({
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

function ScrollToBottomButton({ onPress }: { onPress: () => void }) {
  const { colors, dark } = usePreferences();
  const content = (
    <Pressable
      accessibilityLabel="Scroll to latest message"
      accessibilityRole="button"
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [
        styles.scrollToBottomPressable,
        { opacity: pressed ? 0.7 : 1 },
      ]}
    >
      <Ionicons name="arrow-down" size={18} color={colors.text} />
    </Pressable>
  );

  if (isGlassEffectAPIAvailable()) {
    return (
      <GlassView
        glassEffectStyle="regular"
        colorScheme={dark ? "dark" : "light"}
        isInteractive
        style={styles.scrollToBottomButton}
      >
        {content}
      </GlassView>
    );
  }

  return (
    <View
      style={[
        styles.scrollToBottomButton,
        styles.scrollToBottomFallback,
        { backgroundColor: colors.elevated, borderColor: colors.border },
      ]}
    >
      {content}
    </View>
  );
}

function useTranscriptWordHaptics() {
  const maximumWordCount = useRef(0);
  const lastHapticAt = useRef(0);
  const pendingHaptic = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cancelPendingHaptic = useCallback(() => {
    if (pendingHaptic.current === null) return;
    clearTimeout(pendingHaptic.current);
    pendingHaptic.current = null;
  }, []);

  useEffect(() => cancelPendingHaptic, [cancelPendingHaptic]);

  return useCallback(
    (text: string) => {
      if (process.env.EXPO_OS !== "ios") return;
      const trimmed = text.trim();
      if (!trimmed) {
        maximumWordCount.current = 0;
        cancelPendingHaptic();
        return;
      }

      const wordCount = trimmed.split(/\s+/u).length;
      if (wordCount <= maximumWordCount.current) return;
      maximumWordCount.current = wordCount;

      const pulse = () => {
        pendingHaptic.current = null;
        lastHapticAt.current = Date.now();
        void triggerTranscriptHaptic().catch(() => undefined);
      };
      const remaining =
        TRANSCRIPT_HAPTIC_INTERVAL_MS - (Date.now() - lastHapticAt.current);
      if (remaining <= 0) {
        cancelPendingHaptic();
        pulse();
      } else if (pendingHaptic.current === null) {
        pendingHaptic.current = setTimeout(pulse, remaining);
      }
    },
    [cancelPendingHaptic],
  );
}

export default function ChatPage() {
  const insets = useSafeAreaInsets();
  const { agent, socket, name } = useAgent();
  const { api } = useSession();
  const preferences = usePreferences();
  const { colors } = preferences;
  const showToolCalls = preferences.showToolCallsForAgent(name);
  const [input, setInputState] = useState("");
  const inputValueRef = useRef("");
  const setInput = useCallback((value: string) => {
    inputValueRef.current = value;
    setInputState(value);
  }, []);
  const [replyTarget, setReplyTarget] = useState<ReplyTarget | null>(null);
  const [voiceError, setVoiceError] = useState("");
  const notifyTranscriptWords = useTranscriptWordHaptics();
  const handleTranscript = useCallback(
    (text: string) => {
      setInput(text);
      notifyTranscriptWords(text);
    },
    [notifyTranscriptWords, setInput],
  );
  const inputRef = useRef<ChatComposerInputRef>(null);
  const measuredComposerHeight = useRef<number | null>(null);
  const composerInset = useSharedValue(0);
  const {
    attachList,
    handleScroll,
    isAwayFromLatest,
    renderScrollComponent,
    scrollToLatest,
  } = useInvertedChatScroll<ChatRow>(composerInset);
  const rows = useMemo(
    () =>
      createInvertedChatRows(
        socket.events,
        showToolCalls,
        socket.isTyping,
      ),
    [showToolCalls, socket.events, socket.isTyping],
  );

  const handleComposerLayout = useCallback(
    (event: LayoutChangeEvent) => {
      const height = Math.max(event.nativeEvent.layout.height, 0);
      const previousHeight = measuredComposerHeight.current;
      if (previousHeight !== null && Math.abs(previousHeight - height) < 0.5) {
        return;
      }

      measuredComposerHeight.current = height;
      const inset = height + CHAT_COMPOSER_GAP;
      composerInset.set(
        previousHeight === null
          ? inset
          : withTiming(inset, { duration: COMPOSER_RESIZE_DURATION }),
      );
    },
    [composerInset],
  );
  const loadingOverlayInsetStyle = useAnimatedStyle(() => ({
    paddingBottom: composerInset.value,
  }));
  const hasVoiceService = Boolean(agent && "voice" in agent.services);
  const speechToText = useQuery({
    queryKey: ["voice", name, "stt"],
    queryFn: () => fetchVoiceStatus(api, name, "stt"),
    enabled: Boolean(name && hasVoiceService),
  });
  const voiceEnabled = Boolean(
    speechToText.data?.configured && speechToText.data.enabled,
  );
  const speech = useSpeechPlayer(name, socket.latestLiveChat);
  const speechEnabled = speech.enabled;
  const playSpeech = speech.play;
  const stopSpeech = speech.stop;
  const canSend = socket.connected && agent?.status === "alive";
  const sendCurrentInput = useCallback(
    (source?: "voice") => {
      const text = inputValueRef.current.trim();
      if (!text || !canSend) return;
      const outgoing = replyTarget
        ? `${quotedReply(replyTarget.text)}${text}`
        : text;
      if (socket.send(outgoing, source)) {
        setInput("");
        setReplyTarget(null);
      }
    },
    [canSend, replyTarget, setInput, socket],
  );
  const voice = useLiveVoice({
    name,
    enabled: voiceEnabled,
    onTranscript: handleTranscript,
    onTurnEnd: () => sendCurrentInput("voice"),
    onError: setVoiceError,
  });

  const focusComposer = useCallback(() => {
    setTimeout(() => inputRef.current?.focus(), 250);
  }, []);
  const cancelReply = useCallback(() => setReplyTarget(null), []);
  const replyToMessage = useCallback(
    (text: string, user: boolean) => {
      setReplyTarget({ text, sender: user ? "You" : name });
      focusComposer();
    },
    [focusComposer, name],
  );
  const editAndResend = useCallback(
    (text: string) => {
      setReplyTarget(null);
      setInput(text);
      focusComposer();
    },
    [focusComposer, setInput],
  );
  const readAloud = useCallback(
    (text: string) => {
      void playSpeech(text).catch(() => undefined);
    },
    [playSpeech],
  );
  const renderChatEvent = useCallback<ListRenderItem<ChatRow>>(
    ({ item }) =>
      item.kind === "typing" ? (
        <TypingIndicator
          agentName={name}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
        />
      ) : item.kind === "date" ? (
        <ChatDateHeader timestamp={item.timestamp} />
      ) : (
        <ChatEvent
          event={item.event}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
          endsBubbleGroup={item.endsBubbleGroup}
          canSpeak={speechEnabled}
          onReply={replyToMessage}
          onEditAndResend={editAndResend}
          onReadAloud={readAloud}
        />
      ),
    [
      editAndResend,
      name,
      readAloud,
      replyToMessage,
      speechEnabled,
    ],
  );

  const loadEarlier = () => {
    if (!socket.hasMore || socket.loadingMore) return;
    void socket.loadMore();
  };

  const send = () => {
    sendCurrentInput();
  };

  const hasDraft = input.trim().length > 0;

  const toggleVoice = () => {
    if (process.env.EXPO_OS === "ios") {
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(
        () => undefined,
      );
    }
    setVoiceError("");
    if (voice.active) {
      voice.stop();
    } else {
      stopSpeech();
      void voice.start().catch((cause) => {
        setVoiceError(cause instanceof Error ? cause.message : "Voice could not start.");
      });
    }
  };

  return (
    <View style={styles.screen}>
      <FlatList
        ref={attachList}
        data={rows}
        inverted
        keyExtractor={(row) => row.key}
        renderItem={renderChatEvent}
        contentContainerStyle={[
          styles.listContent,
          {
            paddingBottom: insets.top + 104,
            flexGrow: rows.length === 0 ? 1 : undefined,
          },
        ]}
        keyboardShouldPersistTaps="handled"
        scrollEnabled={socket.historyLoaded || rows.length > 0}
        renderScrollComponent={renderScrollComponent}
        onScroll={handleScroll}
        scrollEventThrottle={16}
        onEndReached={loadEarlier}
        onEndReachedThreshold={0.1}
        ListFooterComponent={
          socket.loadingMore ? (
            <View style={styles.loadingMore}>
              <ActivityIndicator color={colors.interactive} />
            </View>
          ) : null
        }
        ListEmptyComponent={
          socket.historyLoaded ? (
            <View style={styles.empty}>
              <Text family="heading" style={[styles.emptyTitle, { color: colors.text }]}>Start a conversation</Text>
              <Text style={[styles.emptyDetail, { color: colors.secondaryText }]}>Tell {name} what you want to accomplish.</Text>
            </View>
          ) : null
        }
      />
      {!socket.historyLoaded && rows.length === 0 ? (
        <Reanimated.View
          pointerEvents="none"
          style={[styles.loadingOverlay, loadingOverlayInsetStyle]}
        >
          <ChatLoadingSkeleton />
        </Reanimated.View>
      ) : null}
      <KeyboardStickyView
        offset={{ closed: 0, opened: Math.max(insets.bottom - 8, 0) }}
        pointerEvents="box-none"
        style={styles.composerOverlay}
      >
        <View onLayout={handleComposerLayout}>
        {voiceError ? (
          <View
            style={[styles.voiceError, { backgroundColor: colors.elevated }]}
          >
            <Text style={{ color: colors.danger }}>{voiceError}</Text>
          </View>
        ) : null}
        <View
          style={[
            styles.composerDock,
            { paddingBottom: Math.max(insets.bottom, 8) },
          ]}
        >
          {isAwayFromLatest ? (
            <View pointerEvents="box-none" style={styles.scrollToBottomSlot}>
              <ScrollToBottomButton onPress={scrollToLatest} />
            </View>
          ) : null}
          <ComposerSurface>
            {replyTarget ? (
              <ReplyPreview
                target={replyTarget}
                onCancel={cancelReply}
              />
            ) : null}
            <View style={styles.composerRow}>
              <ChatComposerInput
                ref={inputRef}
                maxLength={20_000}
                onChangeText={setInput}
                placeholder={
                  voice.active
                    ? "Listening…"
                    : canSend
                      ? `Message ${name}`
                      : "Waiting for agent…"
                }
                placeholderTextColor={colors.tertiaryText}
                selectionColor={colors.accent}
                textColor={colors.text}
                value={input}
              />
              <ComposerActionButton
                canSend={canSend}
                hasDraft={hasDraft}
                voiceActive={voice.active}
                voiceEnabled={voiceEnabled}
                onSend={send}
                onToggleVoice={toggleVoice}
              />
            </View>
          </ComposerSurface>
        </View>
        </View>
      </KeyboardStickyView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  listContent: { paddingHorizontal: 12 },
  loadingOverlay: {
    position: "absolute",
    zIndex: 1,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    paddingHorizontal: 12,
  },
  dateHeader: {
    alignSelf: "center",
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginVertical: 8,
  },
  dateHeaderText: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: "600",
    textAlign: "center",
  },
  messageRow: { width: "100%", marginVertical: 3 },
  newBubbleGroup: { marginTop: 13 },
  userRow: { alignItems: "flex-end" },
  agentRow: { alignItems: "flex-start" },
  bubbleMenu: { maxWidth: "88%" },
  bubble: {
    position: "relative",
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  bubbleFallback: {
    borderRadius: radii.bubble,
    borderCurve: "continuous",
  },
  bubbleTail: {
    position: "absolute",
    bottom: 0,
    overflow: "visible",
  },
  userBubbleTail: { right: -5 },
  agentBubbleTail: { left: -6 },
  typingBubble: {
    position: "relative",
    width: 56,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: radii.bubble,
    borderCurve: "continuous",
  },
  typingDots: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  typingDot: { width: 6, height: 6, borderRadius: 3 },
  userText: { fontSize: 16, lineHeight: 22 },
  timestampSpacer: { fontSize: 12, opacity: 0 },
  bubbleTimestamp: { position: "absolute", right: 12, bottom: 10, fontSize: 12 },
  finalMarkdownParagraph: { marginBottom: 0 },
  markdownBlockquote: { paddingRight: 9 },
  markdownBlockquoteParagraph: { marginTop: 0, marginBottom: 0 },
  systemMessage: { textAlign: "center", fontSize: 12, marginVertical: 10 },
  tool: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    maxWidth: "72%",
    borderRadius: 8,
    borderCurve: "continuous",
    paddingHorizontal: 7,
    paddingVertical: 4,
    gap: 4,
  },
  toolText: { flexShrink: 1, fontSize: 10, lineHeight: 13 },
  loadingMore: { height: 44, alignItems: "center", justifyContent: "center" },
  empty: { minHeight: 300, justifyContent: "center", alignItems: "center", gap: 7, padding: 30 },
  emptyTitle: { fontSize: 21, fontWeight: "500" },
  emptyDetail: { fontSize: 14, textAlign: "center" },
  voiceError: { marginHorizontal: 12, paddingHorizontal: 13, paddingVertical: 8, borderRadius: 12 },
  composerOverlay: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, zIndex: 2, justifyContent: "flex-end" },
  composerDock: { paddingHorizontal: 22, paddingTop: 8 },
  scrollToBottomSlot: { position: "absolute", top: -36, right: 0, left: 0, zIndex: 3, alignItems: "center" },
  scrollToBottomButton: { width: 34, height: 34, borderRadius: 17, overflow: "hidden" },
  scrollToBottomPressable: { flex: 1, alignItems: "center", justifyContent: "center" },
  scrollToBottomFallback: { borderWidth: StyleSheet.hairlineWidth },
  composerSurface: {
    padding: COMPOSER_SURFACE_PADDING,
    borderRadius: 22,
    overflow: "hidden",
  },
  composerRow: { flexDirection: "row", alignItems: "flex-end" },
  composerFallback: { borderWidth: StyleSheet.hairlineWidth },
  replyPreview: { flexDirection: "row", alignItems: "center", gap: 8, margin: 3, marginBottom: 6, paddingLeft: 9, paddingRight: 3, paddingVertical: 7, borderRadius: 16, borderCurve: "continuous" },
  replyAccent: { alignSelf: "stretch", width: 3, borderRadius: 2 },
  replyCopy: { flex: 1, minWidth: 0, gap: 1 },
  replyLabel: { fontSize: 12, fontWeight: "600" },
  replyText: { fontSize: 13, lineHeight: 17 },
  replyClose: { width: 28, height: 28, borderRadius: 14, alignItems: "center", justifyContent: "center" },
  roundButton: {
    width: 32,
    height: 32,
    marginBottom: 2,
    borderRadius: 16,
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
    borderRadius: 16,
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
