import {
  forwardRef,
  memo,
  useCallback,
  useMemo,
  useRef,
  useState,
  type ComponentRef,
  type ReactNode,
} from "react";
import {
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
import type { VestaEvent } from "@/api/types";
import { fetchVoiceStatus } from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import { Text, TextInput } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { fontNames } from "@/theme/typography";
import { radii } from "@/theme/layout";
import { useLiveVoice, useSpeechPlayer } from "@/voice/useLiveVoice";

interface ChatRow {
  key: string;
  event: VestaEvent;
  startsNewBubbleGroup: boolean;
  endsBubbleGroup: boolean;
}

const INPUT_HEIGHT = 42;
const COMPOSER_MARGIN = 8;

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

function chatRows(events: VestaEvent[], showToolCalls: boolean): ChatRow[] {
  const visible = events.filter(
    (event) =>
      event.type === "user" ||
      event.type === "chat" ||
      event.type === "error" ||
      event.type === "rate_limited" ||
      (showToolCalls &&
        event.type === "tool_start" &&
        !(event.tool === "Bash" && event.input.includes("app-chat"))),
  );
  const seen = new Map<string, number>();
  let previousBubbleType: "user" | "chat" | null = null;
  const rows = visible.map((event) => {
    const base = `${event.ts ?? "live"}-${event.type}`;
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    const bubbleType =
      event.type === "user" || event.type === "chat" ? event.type : null;
    const startsNewBubbleGroup = Boolean(
      bubbleType && previousBubbleType && bubbleType !== previousBubbleType,
    );
    if (bubbleType) previousBubbleType = bubbleType;
    return {
      key: count === 0 ? base : `${base}#${count}`,
      event,
      startsNewBubbleGroup,
      endsBubbleGroup: false,
    };
  });
  let nextBubbleType: "user" | "chat" | null = null;
  for (let index = rows.length - 1; index >= 0; index -= 1) {
    const row = rows[index];
    if (!row) continue;
    const bubbleType =
      row.event.type === "user" || row.event.type === "chat"
        ? row.event.type
        : null;
    if (!bubbleType) continue;
    row.endsBubbleGroup =
      nextBubbleType === null || bubbleType !== nextBubbleType;
    nextBubbleType = bubbleType;
  }
  return rows;
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
  return (
    <View
      style={[
        styles.messageRow,
        startsNewBubbleGroup ? styles.newBubbleGroup : null,
        user ? styles.userRow : styles.agentRow,
      ]}
    >
      <View
        style={[
          styles.bubble,
          endsBubbleGroup
            ? user
              ? styles.userBubbleEnd
              : styles.agentBubbleEnd
            : null,
          {
            backgroundColor: user ? colors.accent : colors.card,
            borderColor: user ? "transparent" : colors.border,
          },
        ]}
      >
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
  const list = useRef<FlatList<ChatRow>>(null);
  const insets = useSafeAreaInsets();
  const { agent, socket, name } = useAgent();
  const { api } = useSession();
  const { colors, showToolCalls } = usePreferences();
  const [input, setInput] = useState("");
  const [transcript, setTranscript] = useState("");
  const [voiceError, setVoiceError] = useState("");
  const extraContentPadding = useSharedValue(0);
  const rows = useMemo(
    () => chatRows(socket.events, showToolCalls).reverse(),
    [showToolCalls, socket.events],
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
    ({ item }) => (
      <ChatEvent
        event={item.event}
        startsNewBubbleGroup={item.startsNewBubbleGroup}
        endsBubbleGroup={item.endsBubbleGroup}
      />
    ),
    [],
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

  const send = () => {
    const text = input.trim();
    if (!text || !canSend) return;
    if (socket.send(text)) {
      setInput("");
      requestAnimationFrame(() =>
        list.current?.scrollToOffset({ animated: true, offset: 0 }),
      );
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
        ref={list}
        data={rows}
        inverted
        keyExtractor={(row) => row.key}
        renderItem={renderChatEvent}
        contentContainerStyle={styles.listContent}
        keyboardShouldPersistTaps="handled"
        maintainVisibleContentPosition={{
          minIndexForVisible: 0,
          autoscrollToTopThreshold: 80,
        }}
        renderScrollComponent={renderScrollComponent}
        ListFooterComponent={
          socket.hasMore ? (
            <Pressable disabled={socket.loadingMore} onPress={() => void socket.loadMore()}>
              <Text style={[styles.loadMore, { color: colors.interactive }]}>{socket.loadingMore ? "Loading…" : "Load earlier messages"}</Text>
            </Pressable>
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
  listContent: { paddingHorizontal: 12, paddingTop: 104, paddingBottom: 12 },
  messageRow: { width: "100%", marginVertical: 4 },
  newBubbleGroup: { marginTop: 12 },
  userRow: { alignItems: "flex-end" },
  agentRow: { alignItems: "flex-start" },
  bubble: { position: "relative", maxWidth: "88%", borderRadius: radii.bubble, paddingHorizontal: 13, paddingVertical: 9, borderWidth: StyleSheet.hairlineWidth },
  userBubbleEnd: { borderBottomRightRadius: 7 },
  agentBubbleEnd: { borderBottomLeftRadius: 7 },
  userText: { fontSize: 16, lineHeight: 22 },
  timestampSpacer: { fontSize: 9, opacity: 0 },
  bubbleTimestamp: { position: "absolute", right: 13, bottom: 11, fontSize: 9 },
  finalMarkdownParagraph: { marginBottom: 0 },
  systemMessage: { textAlign: "center", fontSize: 12, marginVertical: 10 },
  tool: { alignSelf: "center", flexDirection: "row", alignItems: "center", maxWidth: "90%", borderRadius: 12, paddingHorizontal: 10, paddingVertical: 7, gap: 6, marginVertical: 3 },
  toolText: { flexShrink: 1, fontSize: 12 },
  loadMore: { textAlign: "center", fontSize: 13, fontWeight: "700", padding: 14 },
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
