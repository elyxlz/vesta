import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useLocation } from "react-router-dom";
import { AnimatePresence, motion as m } from "motion/react";
import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CHAT_CONTENT_COLUMN } from "./content-column";
import { useToast } from "@/stores/use-toast";
import { useLayout } from "@/stores/use-layout";
import { useComposerInset } from "./use-composer-inset";
import { useRoom } from "@/providers/RoomProvider/context";
import { useRoomSocket } from "@/providers/RoomSocketProvider/context";
import { useVoice } from "@/stores/use-voice";
import { useChatDraft } from "@/stores/use-chat-draft";
import { useAttachmentDrafts } from "@/stores/use-attachment-drafts";
import { DropOverlay } from "./DropZone";
import { useFileDrop } from "./DropZone/use-file-drop";
import { AttachmentViewer } from "./AttachmentViewer";
import type { OpenViewerRequest } from "./ChatBubble/AttachmentContent";
import { useIsMobile } from "@/hooks/use-mobile";
import { sheetEase } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { BottomBanner } from "./BottomBanner";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";
import { ChatMessageArea, type ChatScrollHandle } from "./ChatMessageArea";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";
import { agentSubpage } from "@/lib/agent-subpage";
import {
  TRIM_HISTORY_SETTLE_MS,
  agentNeedsUser,
  type InputMethod,
} from "@vesta/core";

// The scrim and top fade enter and leave with the conversation, on the shared sheet curve.
const CONVERSATION_FADE = {
  initial: { opacity: 0 },
  animate: { opacity: 1 },
  exit: { opacity: 0, transition: { duration: 0.27 } },
  transition: { duration: 0.5, ease: sheetEase },
} as const;

interface ChatProps {
  onCollapse?: () => void;
  fullscreen?: boolean;
}

export function Chat({ onCollapse, fullscreen }: ChatProps = {}) {
  const { roomId, kind, label, agents, directAgent } = useRoom();
  // Only a direct room follows one agent's sign-in state; a peer or group message queues on the
  // node, so its composer is always live.
  const notAuthenticated =
    directAgent !== null && agentNeedsUser(directAgent.status);
  // Voice is the direct agent's own service: it has no meaning in a room with several members.
  const direct = kind === "direct";
  const isMobile = useIsMobile();
  const toast = useToast();
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const {
    voiceConfigured,
    recordingMode,
    listening,
    liveTranscript,
    startVoice,
    stopVoice,
    cancelVoice,
    voiceError,
    registerChat,
    clearChat,
  } = useVoice();

  const {
    messages,
    isTyping,
    connected,
    historyLoaded,
    hasMore,
    loadingMore,
    loadMore,
    trimHistory,
    send,
    retry,
    reportSpeaking,
  } = useRoomSocket();

  const [input, setInput] = useChatDraft(roomId);
  const attachments = useAttachmentDrafts(roomId);
  const { dragActive, handlers: dropHandlers } = useFileDrop(
    !notAuthenticated,
    attachments.addFiles,
  );
  const [atBottom, setAtBottom] = useState(true);
  const [viewer, setViewer] = useState<OpenViewerRequest | null>(null);
  const openAttachment = useCallback((request: OpenViewerRequest) => {
    setViewer(request);
  }, []);
  const closeViewer = useCallback(() => {
    setViewer(null);
  }, []);

  useEffect(() => {
    if (!atBottom) return;
    const timer = window.setTimeout(trimHistory, TRIM_HISTORY_SETTLE_MS);
    return () => window.clearTimeout(timer);
  }, [atBottom, trimHistory]);

  // Voice sends go through the same composer semantics as typed ones: ready attachments ride
  // along and clear, so a dictated caption never silently drops the chips the user can see.
  const sendWithDrafts = useCallback(
    (text: string, inputMethod: InputMethod = "voice") => {
      const uploaded = attachments.ready ? attachments.uploaded : undefined;
      const sent = send(text, inputMethod, uploaded);
      if (sent && uploaded) attachments.clear();
      return sent;
    },
    [send, attachments],
  );
  const scrollRef = useRef<ChatScrollHandle>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  useChatKeyboardFocus(textareaRef);

  // The one owner of clearing the composer: the draft AND the autosize's inline height, so a
  // voice mode taking the field over never inherits the height of the text it just dropped.
  const clearComposer = useCallback(() => {
    setInput("");
    const ta = textareaRef.current;
    if (ta) ta.style.height = "auto";
  }, [setInput]);

  // Voice speaks into the direct agent's own chat alone: a room with several members leaves the
  // binding cleared rather than pointing at the chat the user just left.
  useEffect(() => {
    if (!direct) {
      clearChat();
      return;
    }
    registerChat(sendWithDrafts, clearComposer, reportSpeaking);
  }, [
    direct,
    clearChat,
    registerChat,
    sendWithDrafts,
    clearComposer,
    reportSpeaking,
  ]);

  // Focus the composer whenever the chat becomes the visible surface: on mount,
  // and again when a logs/settings subpage closes (the pane stays mounted, so a
  // mount-time autofocus never refires). Skipped on mobile, where autofocus
  // would raise the keyboard on every open. A fullscreen and a panel Chat can
  // both be mounted; focus() is a no-op on the visibility-hidden one.
  const { pathname } = useLocation();
  const agentName = directAgent?.name ?? null;
  useEffect(() => {
    if (isMobile) return;
    if (agentName !== null && agentSubpage(pathname, agentName) !== null)
      return;
    textareaRef.current?.focus({ preventScroll: true });
  }, [isMobile, pathname, agentName]);

  const inConversation = recordingMode === "conversation";
  const {
    cardRef,
    composerRef,
    composerNodeRef,
    composerInset,
    composerHeight,
    composerGap,
    onMorphSettled,
    handleHeightAnimation,
  } = useComposerInset({
    fullscreen,
    isMobile,
    hasDraft: input.length > 0 || attachments.drafts.length > 0,
    inConversation,
  });
  const chatMessages = useMemo(
    () =>
      messages.filter(
        (m) =>
          m.type === "user" ||
          m.type === "chat" ||
          m.type === "error" ||
          m.type === "rate_limited",
      ),
    [messages],
  );

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollToBottom();
  }, []);

  // A conversation owns the viewport: pin the chat to the newest message when it opens and
  // keep it pinned as turns land, whatever the scroll position was before. The inset tracking
  // the morphing panel keeps it pinned through the resize itself.
  // While locked the list is bottom-anchored structurally; on both edges of the lock the
  // real scroller needs to sit at the end (entering: before the anchor kicks in, leaving:
  // the resumed scroller's scrollTop is stale).
  useEffect(() => {
    requestAnimationFrame(() => scrollRef.current?.pinToLatest());
    // The locked list shows only its tail, so drop the rest of the loaded history right
    // away; scrolling up after the conversation refetches it.
    if (inConversation) trimHistory();
  }, [inConversation, trimHistory]);

  // Stable so ChatMessageArea's memo holds across per-keystroke composer re-renders.
  const handleLoadMore = useCallback(() => {
    void loadMore();
  }, [loadMore]);

  // The send gate: text alone sends as before; with drafts present, every one must be uploaded
  // (chips show progress) and the text becomes the optional caption.
  const canSend =
    attachments.drafts.length > 0 ? attachments.ready : input.trim().length > 0;

  const handleSend = () => {
    const text = input.trim();
    if (!canSend) {
      // A closed gate with visible chips deserves a reason, not a silent no-op; an empty
      // composer stays quiet as before.
      if (attachments.drafts.length > 0)
        toast.error(
          attachments.drafts.some((draft) => draft.status === "error")
            ? "retry or remove the failed attachment first"
            : "attachments are still uploading",
        );
      return;
    }
    if (!connected) {
      toast.error(`can't reach ${label} right now, message not sent`);
      return;
    }
    const uploaded = attachments.uploaded;
    if (send(text, "typed", uploaded.length > 0 ? uploaded : undefined)) {
      clearComposer();
      attachments.clear();
      requestAnimationFrame(scrollToBottom);
    }
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      // While a voice mode runs, the field shows the live transcript (not `input`); Enter must
      // not fire a send whose contents differ from what the screen shows.
      if (recordingMode !== null) return;
      handleSend();
    }
  };

  const handlePaste = (e: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = [...e.clipboardData.files];
    if (files.length === 0) return;
    e.preventDefault();
    attachments.addFiles(files);
  };

  const handleInput = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const ta = e.target;
    ta.style.height = "auto";
    ta.style.height = `${String(Math.min(ta.scrollHeight, 240))}px`;
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <Card
        {...dropHandlers}
        ref={cardRef}
        className={cn(
          "flex flex-col h-full gap-0 py-0 px-0 overflow-hidden relative text-base shadow-none",
          fullscreen && "ring-0",
          isMobile && "bg-transparent overflow-visible",
        )}
      >
        <DropOverlay active={dragActive} label={label} />
        <AttachmentViewer request={viewer} onClose={closeViewer} />
        <ChatHeaderActions
          fullscreen={fullscreen}
          receded={inConversation}
          onCollapse={onCollapse}
          agentName={agentName}
        />

        <ChatMessageArea
          scrollRef={scrollRef}
          loadMore={handleLoadMore}
          fullscreen={fullscreen}
          navbarHeight={navbarHeight}
          loadingMore={loadingMore}
          hasMore={hasMore}
          chatMessages={chatMessages}
          connected={connected}
          historyLoaded={historyLoaded}
          label={label}
          showSenders={agents.length > 1}
          notAuthenticated={notAuthenticated}
          isTyping={isTyping}
          isMobile={isMobile}
          scrollLocked={inConversation}
          onRetry={retry}
          onOpenAttachment={openAttachment}
          bottomInset={composerInset + composerGap}
          bottomOverhang={Math.max(0, composerHeight - composerInset)}
          onAtBottomChange={setAtBottom}
        />

        <AnimatePresence>
          {inConversation && (
            <m.button
              type="button"
              aria-label="end conversation"
              onClick={stopVoice}
              {...CONVERSATION_FADE}
              className="absolute inset-0 z-10 cursor-default bg-background/60"
            />
          )}
          {inConversation && (
            <m.div
              aria-hidden
              {...CONVERSATION_FADE}
              className="pointer-events-none absolute inset-x-0 top-0 z-20 h-24 bg-gradient-to-b from-background to-transparent"
            />
          )}
        </AnimatePresence>

        <div
          ref={(node) => {
            composerNodeRef.current = node;
            composerRef(node);
          }}
          // px-3 mirrors the message list's 12px scrollbar-gutter on each side, so the
          // composer's capped column computes from the same width and lines up with the bubbles.
          className={cn(
            "absolute inset-x-0 bottom-0 z-20",
            !isMobile && "px-3",
          )}
        >
          {chatMessages.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Scroll to latest message"
              data-active={!atBottom}
              onClick={scrollToBottom}
              className={cn(
                "absolute bottom-full left-1/2 z-10 mb-3 -translate-x-1/2 rounded-full shadow-sm transition-all duration-200",
                "data-[active=false]:pointer-events-none data-[active=false]:translate-y-full data-[active=false]:scale-95 data-[active=false]:opacity-0 data-[active=false]:duration-150 data-[active=false]:ease-[cubic-bezier(0.7,0,0.84,0)]",
                "data-[active=true]:translate-y-0 data-[active=true]:scale-100 data-[active=true]:opacity-100 data-[active=true]:ease-[cubic-bezier(0.23,1,0.32,1)]",
              )}
            >
              <ArrowDown />
            </Button>
          )}
          <div
            className={cn(
              "relative",
              // The capped centered column is shared by both desktop chats; only mobile fills full width.
              !isMobile && CHAT_CONTENT_COLUMN,
            )}
          >
            <BottomBanner error={voiceError} />
            <ChatComposer
              fullscreen={fullscreen}
              label={label}
              notAuthenticated={notAuthenticated}
              voiceConfigured={direct && voiceConfigured}
              recordingMode={recordingMode}
              listening={listening}
              liveTranscript={liveTranscript}
              onMorphSettled={onMorphSettled}
              onHeightAnimation={handleHeightAnimation}
              startVoice={startVoice}
              stopVoice={stopVoice}
              cancelVoice={cancelVoice}
              input={input}
              onInputChange={handleInput}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              onSend={handleSend}
              canSend={canSend}
              attachments={attachments}
              textareaRef={textareaRef}
            />
          </div>
        </div>
      </Card>
    </div>
  );
}
