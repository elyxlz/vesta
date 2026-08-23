import { useCallback, useMemo, useRef, useState } from "react";
import { StyleSheet, View, type LayoutChangeEvent } from "react-native";
import { useQuery } from "@tanstack/react-query";
import {
  KeyboardStickyView,
  useReanimatedKeyboardAnimation,
} from "react-native-keyboard-controller";
import Animated, {
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from "react-native-reanimated";
import * as Haptics from "expo-haptics";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { fetchVoiceStatus } from "@/api/endpoints";
import { useAgent } from "@/agent/AgentProvider";
import {
  ChatComposerInput,
  type ChatComposerInputRef,
} from "@/components/chat-composer-input";
import { CHAT_COMPOSER_CONTROL_HEIGHT } from "@/components/chat-composer-input.types";
import { useToast } from "@/components/native-toast";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { useLiveVoice, useSpeechPlayer } from "@/voice/useLiveVoice";
import { createInvertedChatRows, type ChatRow } from "@/agent/chat-list-model";
import { quotedReply, type ReplyTarget } from "@/agent/message-actions";
import { useInvertedChatScroll } from "@/agent/use-inverted-chat-scroll";
import { GlassSurface } from "@/components/ui/glass-surface";
import { ComposerActionButton, ReplyPreview } from "@/agent/chat/chat-composer";
import { ChatTranscript } from "@/agent/chat/chat-transcript";
import { ScrollToBottomButton } from "@/agent/chat/scroll-to-bottom-button";
import { useTranscriptWordHaptics } from "@/agent/chat/use-transcript-word-haptics";
import { useAgentHolds } from "@/holds/AgentHoldsProvider";
import { agentHoldKey } from "@/holds/keyed-hold";
import { connectionKeyOf } from "@/session/session-model";

const COMPOSER_RESIZE_DURATION = 250;
const CHAT_COMPOSER_GAP = 6;
const COMPOSER_SURFACE_PADDING = 8;
// Space kept below the composer: above the home indicator while the keyboard
// is closed, and above the keyboard once it is open.
const COMPOSER_CLOSED_GAP = 6;
const COMPOSER_KEYBOARD_GAP = 10;
// The dock sits further inset while the keyboard is closed and widens to
// the chat list edge once it is open, in step with the keyboard's own motion.
const COMPOSER_INSET_CLOSED = 48;
const COMPOSER_INSET_OPEN = 12;

export default function ChatPage() {
  const insets = useSafeAreaInsets();
  const { agent, socket, name } = useAgent();
  const { api, connection } = useSession();
  const { showError } = useToast();
  const { colors } = usePreferences();
  // The draft and armed reply live in a per-agent hold, so popping back to home (or switching
  // agents) never discards half-typed input; a successful send clears the cell via setInput("").
  const holds = useAgentHolds();
  const holdKey = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  const [input, setInputState] = useState(
    () => holds.composer.read(holdKey)?.draft ?? "",
  );
  const inputValueRef = useRef(input);
  const [replyTarget, setReplyTargetState] = useState<ReplyTarget | null>(
    () => holds.composer.read(holdKey)?.replyTarget ?? null,
  );
  const replyTargetRef = useRef(replyTarget);
  const setInput = useCallback(
    (value: string) => {
      inputValueRef.current = value;
      setInputState(value);
      holds.composer.persist(holdKey, {
        draft: value,
        replyTarget: replyTargetRef.current,
      });
    },
    [holds, holdKey],
  );
  const setReplyTarget = useCallback(
    (target: ReplyTarget | null) => {
      replyTargetRef.current = target;
      setReplyTargetState(target);
      holds.composer.persist(holdKey, {
        draft: inputValueRef.current,
        replyTarget: target,
      });
    },
    [holds, holdKey],
  );
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
  // How far the dock drops back toward an open keyboard, so that of its
  // closed bottom padding only the keyboard gap stays above the keys.
  const composerKeyboardOffset =
    insets.bottom + COMPOSER_CLOSED_GAP - COMPOSER_KEYBOARD_GAP;
  const keyboard = useReanimatedKeyboardAnimation();
  const composerDockStyle = useAnimatedStyle(() => ({
    paddingHorizontal: interpolate(
      keyboard.progress.value,
      [0, 1],
      [COMPOSER_INSET_CLOSED, COMPOSER_INSET_OPEN],
    ),
  }));
  const {
    attachList,
    handleScroll,
    isAwayFromLatest,
    renderScrollComponent,
    scrollToLatest,
  } = useInvertedChatScroll<ChatRow>(composerInset, composerKeyboardOffset);
  const rows = useMemo(
    () => createInvertedChatRows(socket.events, socket.isTyping),
    [socket.events, socket.isTyping],
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
  const sendChat = socket.send;
  // Reads the draft and armed reply from their refs, so the voice socket's captured
  // onTurnEnd sends what is armed at turn end, not what was armed at start().
  const sendCurrentInput = useCallback(
    (source?: "voice") => {
      const text = inputValueRef.current.trim();
      if (!text || !canSend) return;
      const reply = replyTargetRef.current;
      const outgoing = reply ? `${quotedReply(reply.text)}${text}` : text;
      if (sendChat(outgoing, source)) {
        setInput("");
        setReplyTarget(null);
      }
    },
    [canSend, sendChat, setInput, setReplyTarget],
  );
  const voice = useLiveVoice({
    name,
    enabled: voiceEnabled,
    onTranscript: handleTranscript,
    onTurnEnd: () => sendCurrentInput("voice"),
    onError: showError,
  });

  const focusComposer = useCallback(() => {
    setTimeout(() => inputRef.current?.focus(), 250);
  }, []);
  const cancelReply = useCallback(() => setReplyTarget(null), [setReplyTarget]);
  const replyToMessage = useCallback(
    (text: string, user: boolean) => {
      setReplyTarget({ text, sender: user ? "You" : name });
      focusComposer();
    },
    [focusComposer, name, setReplyTarget],
  );
  const editAndResend = useCallback(
    (text: string) => {
      setReplyTarget(null);
      setInput(text);
      focusComposer();
    },
    [focusComposer, setInput, setReplyTarget],
  );
  const readAloud = useCallback(
    (text: string) => {
      void playSpeech(text).catch(() => undefined);
    },
    [playSpeech],
  );
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
    if (voice.active) {
      voice.stop();
    } else {
      stopSpeech();
      void voice.start().catch((cause) => {
        showError(cause, "Voice could not start");
      });
    }
  };

  return (
    <View style={styles.screen}>
      <ChatTranscript
        rows={rows}
        agentName={name}
        canSpeak={speechEnabled}
        historyLoaded={socket.historyLoaded}
        loadingMore={socket.loadingMore}
        composerInset={composerInset}
        attachList={attachList}
        onScroll={handleScroll}
        renderScrollComponent={renderScrollComponent}
        onLoadEarlier={socket.loadMore}
        onReply={replyToMessage}
        onEditAndResend={editAndResend}
        onReadAloud={readAloud}
        onRetry={socket.retry}
      />
      <KeyboardStickyView
        offset={{ closed: 0, opened: composerKeyboardOffset }}
        pointerEvents="box-none"
        style={styles.composerOverlay}
      >
        <View onLayout={handleComposerLayout}>
          <Animated.View
            style={[
              styles.composerDock,
              composerDockStyle,
              { paddingBottom: insets.bottom + COMPOSER_CLOSED_GAP },
            ]}
          >
            {isAwayFromLatest && rows.length > 0 ? (
              <View pointerEvents="box-none" style={styles.scrollToBottomSlot}>
                <ScrollToBottomButton onPress={scrollToLatest} />
              </View>
            ) : null}
            <GlassSurface style={styles.composerSurface}>
              {replyTarget ? (
                <ReplyPreview target={replyTarget} onCancel={cancelReply} />
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
            </GlassSurface>
          </Animated.View>
        </View>
      </KeyboardStickyView>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  composerOverlay: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 2,
    justifyContent: "flex-end",
  },
  composerDock: { paddingTop: 8 },
  composerSurface: {
    padding: COMPOSER_SURFACE_PADDING,
    borderRadius: CHAT_COMPOSER_CONTROL_HEIGHT / 2 + COMPOSER_SURFACE_PADDING,
    overflow: "hidden",
  },
  scrollToBottomSlot: {
    position: "absolute",
    top: -36,
    right: 0,
    left: 0,
    zIndex: 3,
    alignItems: "center",
  },
  composerRow: { flexDirection: "row", alignItems: "flex-end" },
});
