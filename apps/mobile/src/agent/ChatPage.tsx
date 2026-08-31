import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { agentHoldKey, TRIM_HISTORY_SETTLE_MS } from "@vesta/core";
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
import { useLiveVoice } from "@/voice/useLiveVoice";
import { createInvertedChatRows, type ChatRow } from "@/agent/chat-list-model";
import { quotedReply, type ReplyTarget } from "@/agent/message-actions";
import { useInvertedChatScroll } from "@/agent/use-inverted-chat-scroll";
import { usePagerScrollLock } from "@/agent/pager-scroll-lock";
import { GlassSurface } from "@/components/ui/glass-surface";
import {
  AttachButton,
  ComposerActions,
  ReplyPreview,
} from "@/agent/chat/chat-composer";
import { AttachmentChips } from "@/agent/chat/attachment-chips";
import { AttachmentViewer } from "@/agent/chat/attachment-viewer";
import type { OpenViewerRequest } from "@/agent/chat/attachment-content";
import { showAttachMenu } from "@/agent/chat/attach-menu";
import { useAttachmentDrafts } from "@/attachments/use-attachment-drafts";
import { VoiceConversationPanel } from "@/agent/chat/voice-conversation-panel";
import { ChatTranscript } from "@/agent/chat/chat-transcript";
import { ScrollToBottomButton } from "@/agent/chat/scroll-to-bottom-button";
import { useTranscriptWordHaptics } from "@/agent/chat/use-transcript-word-haptics";
import { agentHolds } from "@/holds/agent-holds";
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
  const holdKey = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  const [input, setInputState] = useState(
    () => agentHolds.composer.read(holdKey)?.draft ?? "",
  );
  const inputValueRef = useRef(input);
  const [replyTarget, setReplyTargetState] = useState<ReplyTarget | null>(
    () => agentHolds.composer.read(holdKey)?.replyTarget ?? null,
  );
  const replyTargetRef = useRef(replyTarget);
  const setInput = useCallback(
    (value: string) => {
      inputValueRef.current = value;
      setInputState(value);
      agentHolds.composer.persist(holdKey, {
        draft: value,
        replyTarget: replyTargetRef.current,
      });
    },
    [holdKey],
  );
  const setReplyTarget = useCallback(
    (target: ReplyTarget | null) => {
      replyTargetRef.current = target;
      setReplyTargetState(target);
      agentHolds.composer.persist(holdKey, {
        draft: inputValueRef.current,
        replyTarget: target,
      });
    },
    [holdKey],
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
  const lockPagerScroll = usePagerScrollLock();
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
    handleContentSizeChange,
    isAwayFromLatest,
    renderScrollComponent,
    scrollToLatest,
  } = useInvertedChatScroll<ChatRow>(composerInset, composerKeyboardOffset);
  const rows = useMemo(
    () => createInvertedChatRows(socket.events, socket.isTyping),
    [socket.events, socket.isTyping],
  );

  // Settled at the latest message: paged-in history far above the viewport (held for the whole
  // session by the chat hold) is released; scrolling up refetches through the ordinary paging.
  const trimHistory = socket.trimHistory;
  useEffect(() => {
    if (isAwayFromLatest) return;
    const timer = setTimeout(trimHistory, TRIM_HISTORY_SETTLE_MS);
    return () => clearTimeout(timer);
  }, [isAwayFromLatest, trimHistory]);

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
  const canSend = socket.connected && agent?.status === "alive";
  const canSendRef = useRef(canSend);
  useEffect(() => {
    canSendRef.current = canSend;
  });
  const sendChat = socket.send;
  const attachments = useAttachmentDrafts(name, holdKey, api, showError);
  const attachmentsRef = useRef(attachments);
  useEffect(() => {
    attachmentsRef.current = attachments;
  }, [attachments]);
  const [conversationTranscript, setConversationTranscript] = useState("");
  const modeRef = useRef<"dictation" | "conversation" | null>(null);
  // Reads the armed reply and attachments from refs, so a captured turn is sent with whatever is
  // armed at turn end, not at start. Ready chips ride along and clear on any send (typed,
  // dictation confirm, or a conversation turn); chips still uploading stay put while the text
  // sends alone, so no turn is ever silently dropped.
  const sendText = useCallback(
    (text: string, source?: "voice") => {
      const trimmed = text.trim();
      if (!canSendRef.current) return;
      const drafts = attachmentsRef.current;
      const uploaded = drafts.ready ? drafts.uploaded : undefined;
      if (!trimmed && !uploaded) return;
      const reply = replyTargetRef.current;
      const outgoing = reply ? `${quotedReply(reply.text)}${trimmed}` : trimmed;
      if (sendChat(outgoing, source, uploaded)) {
        setInput("");
        setReplyTarget(null);
        if (uploaded) drafts.clear();
      }
    },
    [sendChat, setInput, setReplyTarget],
  );
  const handleVoiceTranscript = useCallback(
    (text: string) => {
      if (modeRef.current === "conversation") setConversationTranscript(text);
      else handleTranscript(text);
    },
    [handleTranscript],
  );
  const voice = useLiveVoice({
    name,
    enabled: voiceEnabled,
    sttStatus: speechToText.data ?? null,
    onTranscript: handleVoiceTranscript,
    // A conversation sends each turn as it ends; dictation sends the composer on confirm
    // (below), so a manual edit made during dictation rides along.
    onSend: (text) => {
      if (modeRef.current === "conversation") sendText(text, "voice");
    },
    onError: showError,
    onInactivityStop: () =>
      showError(
        "Conversation ended after 15 minutes of silence.",
        "Voice conversation",
      ),
  });
  const recordingMode = voice.recordingMode;
  useEffect(() => {
    modeRef.current = recordingMode;
  }, [recordingMode]);
  const speechEnabled = voice.ttsEnabled;
  const speakLatest = voice.speak;
  const spokenRef = useRef<string | null>(null);
  useEffect(() => {
    const latest = socket.latestLiveChat;
    if (latest && latest !== spokenRef.current) {
      spokenRef.current = latest;
      speakLatest(latest);
    }
  }, [socket.latestLiveChat, speakLatest]);

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
      speakLatest(text);
    },
    [speakLatest],
  );
  const send = () => {
    sendText(inputValueRef.current);
  };

  const hasChips = attachments.drafts.length > 0;
  // The send affordance lights up for text or a ready batch of chips; a still-uploading
  // chips-only draft keeps the trailing button in its voice form until the uploads finish.
  const hasDraft = input.trim().length > 0 || attachments.ready;
  const openAttachMenu = useCallback(() => {
    showAttachMenu((assets) => {
      void attachmentsRef.current.addAssets(assets);
    });
  }, []);
  const [viewer, setViewer] = useState<OpenViewerRequest | null>(null);
  const openAttachment = useCallback((request: OpenViewerRequest) => {
    setViewer(request);
  }, []);
  const closeViewer = useCallback(() => {
    setViewer(null);
  }, []);

  const heavyHaptic = () => {
    if (process.env.EXPO_OS === "ios")
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy).catch(
        () => undefined,
      );
  };
  const startDictation = () => {
    heavyHaptic();
    setInput("");
    void voice.start("dictation").catch((cause) => {
      showError(cause, "Voice could not start");
    });
  };
  const confirmDictation = () => {
    const text = inputValueRef.current;
    voice.stop();
    sendText(text, "voice");
    setInput("");
  };
  const cancelDictation = () => {
    voice.cancel();
    setInput("");
  };
  const startConversation = () => {
    heavyHaptic();
    setConversationTranscript("");
    void voice.start("conversation").catch((cause) => {
      showError(cause, "Voice could not start");
    });
  };
  const endConversation = () => voice.stop();
  const conversationState = !voice.listening
    ? "connecting"
    : voice.speaking
      ? "speaking"
      : "listening";

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
        onContentSizeChange={handleContentSizeChange}
        renderScrollComponent={renderScrollComponent}
        onLoadEarlier={socket.loadMore}
        onReply={replyToMessage}
        onEditAndResend={editAndResend}
        onReadAloud={readAloud}
        onRetry={socket.retry}
        onOpenAttachment={openAttachment}
      />
      <AttachmentViewer
        api={api}
        agent={name}
        request={viewer}
        onClose={closeViewer}
      />
      <KeyboardStickyView
        offset={{ closed: 0, opened: composerKeyboardOffset }}
        pointerEvents="box-none"
        style={styles.composerOverlay}
      >
        <View
          onLayout={handleComposerLayout}
          onTouchStart={() => lockPagerScroll(true)}
          onTouchEnd={() => lockPagerScroll(false)}
          onTouchCancel={() => lockPagerScroll(false)}
        >
          <Animated.View
            style={[
              styles.composerDock,
              composerDockStyle,
              { paddingBottom: insets.bottom + COMPOSER_CLOSED_GAP },
            ]}
          >
            <View pointerEvents="box-none" style={styles.scrollToBottomSlot}>
              <ScrollToBottomButton
                visible={isAwayFromLatest && rows.length > 0}
                onPress={scrollToLatest}
              />
            </View>
            <GlassSurface style={styles.composerSurface}>
              {recordingMode === "conversation" ? (
                <VoiceConversationPanel
                  state={conversationState}
                  transcript={conversationTranscript}
                  height={CONVERSATION_PANEL_HEIGHT}
                  onEnd={endConversation}
                />
              ) : (
                <>
                  {replyTarget ? (
                    <ReplyPreview target={replyTarget} onCancel={cancelReply} />
                  ) : null}
                  <AttachmentChips
                    drafts={attachments.drafts}
                    previewUri={attachments.previewUri}
                    onRetry={attachments.retry}
                    onRemove={attachments.remove}
                  />
                  <View style={styles.composerRow}>
                    <AttachButton
                      disabled={!canSend}
                      onPress={openAttachMenu}
                    />
                    <ChatComposerInput
                      ref={inputRef}
                      maxLength={20_000}
                      onChangeText={setInput}
                      placeholder={
                        recordingMode === "dictation"
                          ? "Listening…"
                          : !canSend
                            ? "Waiting for agent…"
                            : hasChips && input.length === 0
                              ? "Add a caption…"
                              : `Message ${name}`
                      }
                      placeholderTextColor={colors.tertiaryText}
                      selectionColor={colors.accent}
                      textColor={colors.text}
                      value={input}
                    />
                    <ComposerActions
                      canSend={canSend}
                      hasDraft={hasDraft}
                      recordingMode={recordingMode}
                      voiceEnabled={voiceEnabled}
                      onSend={send}
                      onDictate={startDictation}
                      onConfirm={confirmDictation}
                      onCancel={cancelDictation}
                      onConversation={startConversation}
                    />
                  </View>
                </>
              )}
            </GlassSurface>
          </Animated.View>
        </View>
      </KeyboardStickyView>
    </View>
  );
}

const CONVERSATION_PANEL_HEIGHT = 220;

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
