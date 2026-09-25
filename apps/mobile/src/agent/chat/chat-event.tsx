import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Animated,
  Easing,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import Markdown, {
  MarkdownIt,
  type ASTNode,
  type RenderRules,
} from "react-native-markdown-display";
import { Ionicons } from "@expo/vector-icons";
import * as Clipboard from "expo-clipboard";
import * as WebBrowser from "expo-web-browser";
import Svg, { Path } from "react-native-svg";
import { formatResetTime } from "@vesta/core";
import type { ChatAttachment, ChatMessage, InputMethod } from "@vesta/core";
import contentCopyIcon from "../../../assets/menu-icons/content-copy.xml";
import editIcon from "../../../assets/menu-icons/edit.xml";
import replyIcon from "../../../assets/menu-icons/reply.xml";
import shareIcon from "../../../assets/menu-icons/share.xml";
import volumeUpIcon from "../../../assets/menu-icons/volume-up.xml";
import { Text } from "@/components/ui/Typography";
import {
  MessageContextMenu,
  type MessageMenuAction,
  type MessageMenuHandle,
} from "@/components/message-context-menu";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { shareVestaMessage } from "@/sharing/share-message";
import { radii } from "@/theme/layout";
import {
  messageActionIds,
  type MessageActionId,
} from "@/agent/message-actions";
import { useSession } from "@/session/SessionProvider";
import { chatMarkdownStyleSet } from "@/agent/chat/chat-markdown";
import {
  AttachmentContent,
  type OpenViewerRequest,
} from "@/agent/chat/attachment-content";
import { CodeBlock } from "@/agent/chat/code-block";
import { QuotedBlock } from "@/agent/chat/quoted-block";
import {
  chatDateLabel,
  isFinalMarkdownNode,
  resolveMarkdownLink,
} from "@/agent/chat/chat-message-model";

const USES_NATIVE_BUBBLE_SHAPE = process.env.EXPO_OS === "ios";

// react-native-markdown-display keeps the fence info string on the node, outside its declared type.
function fenceInfo(node: ASTNode): string | null {
  return "sourceInfo" in node && typeof node.sourceInfo === "string"
    ? node.sourceInfo
    : null;
}
const CHAT_MARKDOWN = new MarkdownIt({
  linkify: true,
  typographer: true,
});

const MESSAGE_ACTIONS: Record<
  MessageActionId,
  MessageMenuAction<MessageActionId>
> = {
  reply: {
    id: "reply",
    title: "Reply",
    systemImage: "arrowshape.turn.up.left",
    androidImage: replyIcon,
  },
  copy: {
    id: "copy",
    title: "Copy",
    systemImage: "doc.on.doc",
    androidImage: contentCopyIcon,
  },
  "edit-resend": {
    id: "edit-resend",
    title: "Edit & Resend",
    systemImage: "pencil",
    androidImage: editIcon,
  },
  "read-aloud": {
    id: "read-aloud",
    title: "Read Aloud",
    systemImage: "speaker.wave.2",
    androidImage: volumeUpIcon,
  },
  share: {
    id: "share",
    title: "Share",
    systemImage: "square.and.arrow.up",
    androidImage: shareIcon,
  },
};

function openMarkdownLink(href: string): boolean {
  const { url, opener } = resolveMarkdownLink(href);
  const open =
    opener === "in-app-browser"
      ? WebBrowser.openBrowserAsync(url)
      : opener === "system"
        ? Linking.openURL(url)
        : Promise.reject(new Error("Unsupported link type"));

  void open.catch(() => {
    Alert.alert("Couldn’t open link", url);
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

export const ChatDateHeader = memo(function ChatDateHeader({
  timestamp,
}: {
  timestamp: string | null;
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

export const ChatEvent = memo(function ChatEvent({
  event,
  agentName,
  startsNewBubbleGroup,
  endsBubbleGroup,
  canSpeak,
  onReply,
  onEditAndResend,
  onReadAloud,
  onRetry,
  onOpenAttachment,
  onMenuOpenChange,
}: {
  event: ChatMessage;
  agentName: string;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
  canSpeak: boolean;
  onReply: (text: string, user: boolean) => void;
  onEditAndResend: (text: string) => void;
  onReadAloud: (text: string) => void;
  onRetry: (
    intentId: string,
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  onOpenAttachment: (request: OpenViewerRequest) => void;
  onMenuOpenChange: (open: boolean) => void;
}) {
  const { colors } = usePreferences();
  const { api } = useSession();
  const { width } = useWindowDimensions();
  // Android's menu wrapper loses the long-press to a pressable attachment block, so blocks get
  // a handler that reopens the menu; iOS's native interaction needs none.
  const menuRef = useRef<MessageMenuHandle | null>(null);
  const openMenuFromBlock = useMemo(
    () =>
      process.env.EXPO_OS === "ios"
        ? undefined
        : () => menuRef.current?.show?.(),
    [],
  );
  // Memoized because toLocaleTimeString builds an Intl formatter per call and
  // rows legitimately re-render (bubble-group flips on each appended message).
  const timestamp = useMemo(
    () =>
      event.ts
        ? new Date(event.ts).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })
        : null,
    [event.ts],
  );
  const user = event.type === "user";
  const markdownRules = useMemo<RenderRules>(
    () => ({
      textgroup: (node, children, parentNodes, markdownStyles) => (
        <Text key={node.key} style={markdownStyles.textgroup}>
          {children}
          {timestamp && isFinalMarkdownNode(node, parentNodes) ? (
            // Android applies neither opacity nor a transparent color to
            // nested Text, so there the spacer hides in the bubble color.
            <Text
              key="timestamp-spacer"
              style={[
                styles.timestampSpacer,
                USES_NATIVE_BUBBLE_SHAPE
                  ? null
                  : { color: user ? colors.accent : colors.bubble },
              ]}
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
      // A table wider than the bubble scrolls sideways instead of clipping columns.
      table: (node, children, parentNodes, markdownStyles) => (
        <View key={node.key}>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.markdownTableScroll}
            contentContainerStyle={styles.markdownTableContent}
          >
            <View style={markdownStyles._VIEW_SAFE_table}>{children}</View>
          </ScrollView>
          {timestamp && isFinalMarkdownNode(node, parentNodes) ? (
            // The absolute timestamp has no text line to share after a block, so an
            // invisible copy reserves its row at the same font scale.
            <Text style={styles.timestampLine}>{timestamp}</Text>
          ) : null}
        </View>
      ),
      fence: (node, _children, parentNodes) => (
        <View key={node.key}>
          <CodeBlock
            code={node.content.replace(/\n$/, "")}
            info={fenceInfo(node)}
            onLongPress={openMenuFromBlock}
          />
          {timestamp && isFinalMarkdownNode(node, parentNodes) ? (
            <Text style={styles.timestampLine}>{timestamp}</Text>
          ) : null}
        </View>
      ),
      code_block: (node, _children, parentNodes) => (
        <View key={node.key}>
          <CodeBlock
            code={node.content.replace(/\n$/, "")}
            info={null}
            onLongPress={openMenuFromBlock}
          />
          {timestamp && isFinalMarkdownNode(node, parentNodes) ? (
            <Text style={styles.timestampLine}>{timestamp}</Text>
          ) : null}
        </View>
      ),
      blockquote: (node, children) => (
        <QuotedBlock
          key={node.key}
          style={styles.markdownBlockquote}
          onAccent={user}
        >
          {children}
        </QuotedBlock>
      ),
    }),
    [colors.accent, colors.bubble, openMenuFromBlock, timestamp, user],
  );
  const markdownStyleSet = chatMarkdownStyleSet(colors);
  const sendState = event.type === "user" ? event.send_state : undefined;
  const intentId = event.type === "user" ? event.intent_id : undefined;
  const messageText = "text" in event ? event.text : "";
  const actions = useMemo<MessageMenuAction<MessageActionId>[]>(
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
    const text =
      event.type === "rate_limited"
        ? event.resets_at != null
          ? `Rate limited. Vesta will be back ${formatResetTime(event.resets_at)}.`
          : "Rate limited. Vesta will be back soon."
        : "This message may not have gone through.";
    return (
      <Text style={[styles.systemMessage, { color: colors.tertiaryText }]}>
        {text}
      </Text>
    );
  }
  if (event.type !== "user" && event.type !== "chat") return null;
  const bubbleColor = user ? colors.accent : colors.bubble;
  const attachments = event.attachments ?? [];
  // With no caption the markdown (and the spacer that reserves the timestamp's room) is absent,
  // so the timestamp renders as its own right-aligned line under the blocks instead.
  const hasCaption = event.text.trim().length > 0;
  const bubble = (
    <View
      accessibilityHint="Long press for message actions"
      style={[
        styles.bubble,
        // Compose's menu trigger measures its RN child independently; the
        // outer percentage maxWidth cannot constrain that measurement.
        USES_NATIVE_BUBBLE_SHAPE ? null : { maxWidth: (width - 24) * 0.88 },
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
      {attachments.map((attachment) => (
        <AttachmentContent
          key={attachment.id}
          api={api}
          agent={agentName}
          user={user}
          attachment={attachment}
          onOpen={onOpenAttachment}
          onLongPress={openMenuFromBlock}
        />
      ))}
      {hasCaption ? (
        <Markdown
          markdownit={CHAT_MARKDOWN}
          onLinkPress={openMarkdownLink}
          rules={markdownRules}
          style={user ? markdownStyleSet.user : markdownStyleSet.base}
        >
          {event.text}
        </Markdown>
      ) : null}
      {timestamp && !hasCaption ? (
        <Text
          style={[
            styles.attachmentTimestamp,
            {
              color: user ? colors.accentText : colors.tertiaryText,
              opacity: user ? 0.58 : 1,
            },
          ]}
        >
          {timestamp}
        </Text>
      ) : null}
      {timestamp && hasCaption ? (
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
  const failed = sendState === "failed" || sendState === "retry";
  return (
    <View
      style={[
        styles.messageRow,
        startsNewBubbleGroup ? styles.newBubbleGroup : null,
        user ? styles.userRow : styles.agentRow,
      ]}
    >
      {failed && intentId ? (
        <Pressable
          accessibilityLabel="Not delivered. Tap to retry"
          accessibilityRole="button"
          hitSlop={8}
          onPress={() =>
            onRetry(
              intentId,
              messageText,
              event.type === "user" ? event.input_method : undefined,
              event.type === "user" ? event.attachments : undefined,
            )
          }
          style={styles.retryMark}
        >
          <Ionicons name="alert-circle" size={20} color={colors.danger} />
        </Pressable>
      ) : null}
      <MessageContextMenu
        actions={actions}
        menuRef={menuRef}
        bubbleFillColor={bubbleColor}
        bubbleStrokeColor={user ? "transparent" : colors.border}
        bubbleStrokeWidth={user ? 0 : StyleSheet.hairlineWidth}
        onAction={performAction}
        onOpenChange={onMenuOpenChange}
        previewCornerRadius={radii.bubble}
        style={styles.bubbleMenu}
        tailOverhang={endsBubbleGroup ? (user ? 5 : 6) : 0}
        tailSide={endsBubbleGroup ? (user ? "trailing" : "leading") : "none"}
      >
        {bubble}
      </MessageContextMenu>
    </View>
  );
});

export const TypingIndicator = memo(function TypingIndicator({
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
            backgroundColor: colors.bubble,
            borderColor: colors.border,
            borderWidth: StyleSheet.hairlineWidth,
          },
        ]}
      >
        <BubbleTail user={false} fill={colors.bubble} stroke={colors.border} />
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

const styles = StyleSheet.create({
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
  // A row, so a failed send's pill sits beside the bubble instead of under it.
  messageRow: {
    width: "100%",
    marginVertical: 3,
    flexDirection: "row",
    alignItems: "center",
  },
  newBubbleGroup: { marginTop: 13 },
  userRow: { justifyContent: "flex-end" },
  agentRow: { justifyContent: "flex-start" },
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
  timestampSpacer: { fontSize: 12, opacity: 0 },
  bubbleTimestamp: {
    position: "absolute",
    right: 12,
    bottom: 10,
    fontSize: 12,
  },
  attachmentTimestamp: { fontSize: 12, textAlign: "right", paddingTop: 2 },
  finalMarkdownParagraph: { marginBottom: 0 },
  markdownBlockquote: { paddingRight: 9 },
  markdownBlockquoteParagraph: { marginTop: 0, marginBottom: 0 },
  markdownTableScroll: { flexGrow: 0, maxWidth: "100%" },
  markdownTableContent: { flexGrow: 1 },
  timestampLine: { fontSize: 12, opacity: 0 },
  systemMessage: { textAlign: "center", fontSize: 12, marginVertical: 10 },
  retryMark: { marginRight: 8 },
});
