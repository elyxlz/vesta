import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentRef,
  type ReactNode,
} from "react";
import {
  ActivityIndicator,
  Animated,
  Easing,
  FlatList,
  Pressable,
  StyleSheet,
  View,
  type LayoutChangeEvent,
  type ListRenderItem,
  type ScrollViewProps,
} from "react-native";
import { useQuery } from "@tanstack/react-query";
import {
  KeyboardChatScrollView,
  KeyboardStickyView,
  type KeyboardChatScrollViewProps,
} from "react-native-keyboard-controller";
import { useSharedValue, withTiming } from "react-native-reanimated";
import Markdown, {
  type ASTNode,
  type RenderRules,
} from "react-native-markdown-display";
import { Ionicons } from "@expo/vector-icons";
import { GlassView, isGlassEffectAPIAvailable } from "expo-glass-effect";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import Svg, { Path } from "react-native-svg";
import type { VestaEvent } from "@/api/types";
import { fetchVoiceStatus } from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { Text, TextInput } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { fontNames } from "@/theme/typography";
import { radii } from "@/theme/layout";
import { useLiveVoice, useSpeechPlayer } from "@/voice/useLiveVoice";
import {
  createInvertedChatRows,
  type ChatRow,
} from "@/agent/chat-list-model";

const INPUT_HEIGHT = 42;
const COMPOSER_MARGIN = 8;
const BUBBLE_TAIL_WIDTH = 6;

type ChatScrollViewRef = ComponentRef<typeof KeyboardChatScrollView>;

const NativeChatScrollView = forwardRef<
  ChatScrollViewRef,
  ScrollViewProps & KeyboardChatScrollViewProps
>(({ inverted, ...props }, ref) => {
  const { bottom } = useSafeAreaInsets();

  return (
    <KeyboardChatScrollView
      ref={ref}
      automaticallyAdjustContentInsets={false}
      contentInsetAdjustmentBehavior="never"
      inverted={inverted}
      keyboardDismissMode="interactive"
      keyboardLiftBehavior="whenAtEnd"
      offset={Math.max(bottom - COMPOSER_MARGIN, 0)}
      {...props}
    />
  );
});
NativeChatScrollView.displayName = "NativeChatScrollView";

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

function bubblePath(
  width: number,
  height: number,
  user: boolean,
  withTail: boolean,
): string {
  const tail = withTail ? BUBBLE_TAIL_WIDTH : 0;
  const left = withTail && !user ? tail - 5 : 0;
  const right = withTail
    ? user
      ? width + 5
      : tail + width
    : width;
  const radius = Math.min(radii.bubble, width / 2, height / 2);

  if (!withTail) {
    return [
      `M ${left + radius} 0`,
      `H ${right - radius}`,
      `Q ${right} 0 ${right} ${radius}`,
      `V ${height - radius}`,
      `Q ${right} ${height} ${right - radius} ${height}`,
      `H ${left + radius}`,
      `Q ${left} ${height} ${left} ${height - radius}`,
      `V ${radius}`,
      `Q ${left} 0 ${left + radius} 0`,
      "Z",
    ].join(" ");
  }

  if (user) {
    return [
      `M ${right - 20} ${height}`,
      `H 15`,
      `C 8 ${height} 0 ${height - 8} 0 ${height - 15}`,
      "V 15",
      "C 0 8 8 0 15 0",
      `H ${right - 20}`,
      `C ${right - 12} 0 ${right - 5} 8 ${right - 5} 15`,
      `V ${height - 12}`,
      `C ${right - 5} ${height - 1} ${right} ${height} ${right} ${height}`,
      `H ${right + 1}`,
      `C ${right - 4} ${height + 1} ${right - 8} ${height - 1} ${right - 12} ${height - 4}`,
      `C ${right - 15} ${height} ${right - 20} ${height} ${right - 20} ${height}`,
      "Z",
    ].join(" ");
  }

  return [
    `M ${left + 20} ${height}`,
    `H ${right - 15}`,
    `C ${right - 8} ${height} ${right} ${height - 8} ${right} ${height - 15}`,
    "V 15",
    `C ${right} 8 ${right - 8} 0 ${right - 15} 0`,
    `H ${left + 20}`,
    `C ${left + 12} 0 ${left + 5} 8 ${left + 5} 15`,
    `V ${height - 10}`,
    `C ${left + 5} ${height - 1} ${left} ${height} ${left} ${height}`,
    `H ${left - 1}`,
    `C ${left + 4} ${height + 1} ${left + 8} ${height - 1} ${left + 12} ${height - 4}`,
    `C ${left + 15} ${height} ${left + 20} ${height} ${left + 20} ${height}`,
    "Z",
  ].join(" ");
}

function BubbleShape({
  width,
  height,
  user,
  withTail,
  fill,
  stroke,
}: {
  width: number;
  height: number;
  user: boolean;
  withTail: boolean;
  fill: string;
  stroke: string;
}) {
  if (width <= 0 || height <= 0) return null;
  const tail = withTail ? BUBBLE_TAIL_WIDTH : 0;

  return (
    <Svg
      pointerEvents="none"
      width={width + tail}
      height={height}
      viewBox={`0 0 ${width + tail} ${height}`}
      style={[styles.bubbleShape, { left: user ? 0 : -tail }]}
    >
      <Path
        d={bubblePath(width, height, user, withTail)}
        fill={fill}
        stroke={user ? "none" : stroke}
        strokeWidth={StyleSheet.hairlineWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </Svg>
  );
}

const ChatEvent = memo(function ChatEvent({
  event,
  startsNewBubbleGroup,
  endsBubbleGroup,
}: {
  event: VestaEvent;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
}) {
  const { colors } = usePreferences();
  const [bubbleSize, setBubbleSize] = useState({ width: 0, height: 0 });
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
            isFinalMarkdownNode(node, parentNodes)
              ? styles.finalMarkdownParagraph
              : null,
          ]}
        >
          {children}
        </View>
      ),
    }),
    [timestamp],
  );
  const handleBubbleLayout = useCallback((event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setBubbleSize((current) =>
      current.width === width && current.height === height
        ? current
        : { width, height },
    );
  }, []);
  if (event.type === "error" || event.type === "rate_limited") {
    const text = event.type === "rate_limited" ? "Rate limited. Vesta will be back soon." : "This message may not have gone through.";
    return <Text style={[styles.systemMessage, { color: colors.tertiaryText }]}>{text}</Text>;
  }
  if (event.type === "tool_start") {
    return (
      <View style={[styles.tool, { backgroundColor: colors.input }]}>
        <Ionicons name="hammer-outline" size={14} color={colors.secondaryText} />
        <Text family="mono" numberOfLines={2} style={[styles.toolText, { color: colors.secondaryText }]}>{event.tool}: {event.input}</Text>
      </View>
    );
  }
  if (event.type !== "user" && event.type !== "chat") return null;
  const user = event.type === "user";
  const bubbleColor = user ? colors.accent : colors.card;
  return (
    <View
      style={[
        styles.messageRow,
        startsNewBubbleGroup ? styles.newBubbleGroup : null,
        user ? styles.userRow : styles.agentRow,
      ]}
    >
      <View onLayout={handleBubbleLayout} style={styles.bubble}>
        <BubbleShape
          width={bubbleSize.width}
          height={bubbleSize.height}
          user={user}
          withTail={endsBubbleGroup}
          fill={bubbleColor}
          stroke={colors.border}
        />
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
            rules={markdownRules}
            style={{
              body: { color: colors.text, fontFamily: fontNames.sans.native["400"], fontSize: 16, lineHeight: 23 },
              strong: { fontFamily: fontNames.sans.native["700"] },
              paragraph: { marginTop: 0, marginBottom: 8 },
              link: { color: colors.interactive },
              code_inline: {
                color: colors.text,
                fontFamily: fontNames.mono.native["400"],
                backgroundColor: colors.code,
                borderRadius: 5,
                paddingHorizontal: 4,
              },
              fence: {
                color: colors.text,
                fontFamily: fontNames.mono.native["400"],
                backgroundColor: colors.code,
                borderColor: colors.border,
                borderRadius: 10,
                padding: 10,
              },
            }}
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
      <View style={styles.typingBubble}>
        <BubbleShape
          width={56}
          height={36}
          user={false}
          withTail
          fill={colors.card}
          stroke={colors.border}
        />
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

export default function ChatPage() {
  const insets = useSafeAreaInsets();
  const { agent, socket, name } = useAgent();
  const { api } = useSession();
  const { colors, showToolCalls } = usePreferences();
  const [input, setInput] = useState("");
  const [transcript, setTranscript] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const extraContentPadding = useSharedValue(0);
  const rows = useMemo(
    () =>
      createInvertedChatRows(
        socket.events,
        showToolCalls,
        socket.isTyping,
      ),
    [showToolCalls, socket.events, socket.isTyping],
  );

  const renderScrollComponent = useCallback(
    (props: ScrollViewProps) => (
      <NativeChatScrollView
        {...props}
        extraContentPadding={extraContentPadding}
      />
    ),
    [extraContentPadding],
  );
  const renderChatEvent = useCallback<ListRenderItem<ChatRow>>(
    ({ item }) =>
      item.kind === "typing" ? (
        <TypingIndicator
          agentName={name}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
        />
      ) : (
        <ChatEvent
          event={item.event}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
          endsBubbleGroup={item.endsBubbleGroup}
        />
      ),
    [name],
  );
  const handleInputLayout = useCallback(
    (event: LayoutChangeEvent) => {
      extraContentPadding.set(withTiming(
        Math.max(event.nativeEvent.layout.height - INPUT_HEIGHT, 0),
        { duration: 250 },
      ));
    },
    [extraContentPadding],
  );
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
  const voice = useLiveVoice({
    name,
    onTranscript: setTranscript,
    onTurnEnd: (text) => {
      if (!socket.send(text, "voice")) setInput(text);
    },
    onError: setVoiceError,
  });
  const canSend = socket.connected && agent?.status === "alive";

  const loadEarlier = () => {
    if (!socket.hasMore || socket.loadingMore) return;
    void socket.loadMore();
  };

  const send = () => {
    const text = input.trim();
    if (!text || !canSend) return;
    if (socket.send(text)) {
      setInput("");
    }
  };

  const toggleVoice = () => {
    setVoiceError("");
    if (voice.active) {
      voice.stop();
    } else {
      speech.stop();
      void voice.start().catch((cause) => {
        setVoiceError(cause instanceof Error ? cause.message : "Voice could not start.");
      });
    }
  };

  return (
    <View style={styles.screen}>
      <FlatList
        data={rows}
        inverted
        keyExtractor={(row) => row.key}
        renderItem={renderChatEvent}
        contentContainerStyle={[
          styles.listContent,
          { paddingBottom: insets.top + 104 },
        ]}
        keyboardShouldPersistTaps="handled"
        renderScrollComponent={renderScrollComponent}
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
      <KeyboardStickyView
        offset={{ closed: 0, opened: Math.max(insets.bottom - 8, 0) }}
        pointerEvents="box-none"
        style={styles.composerOverlay}
      >
        {transcript || voiceError ? (
          <View style={[styles.transcript, { backgroundColor: colors.elevated }]}>
            <Text style={{ color: voiceError ? colors.danger : colors.secondaryText }}>{voiceError || transcript}</Text>
          </View>
        ) : null}
        <View
          style={[
            styles.composerDock,
            { paddingBottom: Math.max(insets.bottom, 8) },
          ]}
        >
          <ComposerSurface>
            {voiceEnabled ? (
              <Pressable
                accessibilityLabel={voice.active ? "Stop listening" : "Start voice input"}
                disabled={!canSend}
                onPress={toggleVoice}
                style={[
                  styles.roundButton,
                  { backgroundColor: voice.active ? colors.danger : "transparent", opacity: canSend ? 1 : 0.4 },
                ]}
              >
                <Ionicons name={voice.active ? "stop" : "mic"} size={18} color={voice.active ? "white" : colors.text} />
              </Pressable>
            ) : null}
            <TextInput
              style={[styles.input, { color: colors.text }]}
              placeholder={canSend ? `Message ${name}` : "Waiting for agent…"}
              placeholderTextColor={colors.tertiaryText}
              value={input}
              onChangeText={setInput}
              multiline
              maxLength={20_000}
              editable={canSend}
              selectionColor={colors.accent}
              onLayout={handleInputLayout}
            />
            <Pressable
              accessibilityLabel="Send message"
              disabled={!canSend || !input.trim()}
              onPress={send}
              style={[
                styles.roundButton,
                { backgroundColor: colors.accent, opacity: canSend && input.trim() ? 1 : 0.38 },
              ]}
            >
              <Ionicons name="arrow-up" size={19} color={colors.accentText} />
            </Pressable>
          </ComposerSurface>
        </View>
      </KeyboardStickyView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  listContent: { paddingHorizontal: 12, paddingTop: 104 },
  messageRow: { width: "100%", marginVertical: 3 },
  newBubbleGroup: { marginTop: 13 },
  userRow: { alignItems: "flex-end" },
  agentRow: { alignItems: "flex-start" },
  bubble: { position: "relative", maxWidth: "88%", paddingHorizontal: 12, paddingVertical: 8 },
  bubbleShape: {
    position: "absolute",
    top: 0,
    overflow: "visible",
  },
  typingBubble: {
    position: "relative",
    width: 56,
    height: 36,
    alignItems: "center",
    justifyContent: "center",
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
  systemMessage: { textAlign: "center", fontSize: 12, marginVertical: 10 },
  tool: { alignSelf: "center", flexDirection: "row", alignItems: "center", maxWidth: "90%", borderRadius: 12, paddingHorizontal: 10, paddingVertical: 7, gap: 6, marginVertical: 3 },
  toolText: { flexShrink: 1, fontSize: 12 },
  loadingMore: { height: 44, alignItems: "center", justifyContent: "center" },
  empty: { minHeight: 300, justifyContent: "center", alignItems: "center", gap: 7, padding: 30 },
  emptyTitle: { fontSize: 21, fontWeight: "500" },
  emptyDetail: { fontSize: 14, textAlign: "center" },
  transcript: { marginHorizontal: 12, paddingHorizontal: 13, paddingVertical: 8, borderRadius: 12 },
  composerOverlay: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, zIndex: 2, justifyContent: "flex-end" },
  composerDock: { paddingHorizontal: 10, paddingTop: 8 },
  composerSurface: { flexDirection: "row", alignItems: "flex-end", gap: 4, padding: 5, borderRadius: 26, overflow: "hidden" },
  composerFallback: { borderWidth: StyleSheet.hairlineWidth },
  input: { flex: 1, minHeight: 42, maxHeight: 180, paddingHorizontal: 10, paddingTop: 11, paddingBottom: 11, fontSize: 16, lineHeight: 20 },
  roundButton: { width: 38, height: 38, marginBottom: 2, borderRadius: 19, alignItems: "center", justifyContent: "center" },
});
