import {
  useCallback,
  useEffect,
  useLayoutEffect,
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
import { useLayout, type ComposerVariant } from "@/stores/use-layout";
import { useAgentSocket } from "@/providers/AgentSocketProvider/context";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useVoice } from "@/stores/use-voice";
import { useChatDraft } from "@/stores/use-chat-draft";
import { useAttachmentDrafts } from "@/stores/use-attachment-drafts";
import { DropOverlay } from "./DropZone";
import { useFileDrop } from "./DropZone/use-file-drop";
import { AttachmentViewer } from "./AttachmentViewer";
import type { OpenViewerRequest } from "./ChatBubble/AttachmentContent";
import { useIsMobile } from "@/hooks/use-mobile";
import { useMeasuredSize } from "@/hooks/use-measured-size";
import { sheetEase } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { BottomBanner } from "./BottomBanner";
import { ChatComposer } from "./ChatComposer";
import { ChatHeaderActions } from "./ChatHeaderActions";

import { ChatMessageArea, type ChatScrollHandle } from "./ChatMessageArea";
import { useChatKeyboardFocus } from "./use-chat-keyboard-focus";
import { agentSubpage } from "@/lib/agent-subpage";
import { TRIM_HISTORY_SETTLE_MS, agentNeedsUser } from "@vesta/core";
import type { InputMethod } from "@vesta/core";

// Breathing room between the last bubble and the floating composer, folded into
// the inset so the message list, skeleton, mask, and button all clear it.
const COMPOSER_GAP_FULLSCREEN_PX = 12;
const COMPOSER_GAP_PANEL_PX = 8;

// The empty composer's height per layout, a CSS-deterministic baseline: the 50px
// pill (a 36px button row plus its 6+6px padding and 2px border) plus the
// wrapper's bottom gap (pb-3 12 / pb-4 16 / pb-1 4). Seeds a cold remount so the
// list reserves the composer's space on its first render; the real measurement
// then overwrites it.
const COMPOSER_BASELINE_PX: Record<ComposerVariant, number> = {
  panel: 62,
  fullscreen: 66,
  mobile: 54,
};

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
  const { name, agent } = useSelectedAgent();
  const notAuthenticated = agentNeedsUser(agent.status);
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
  } = useAgentSocket();

  const [input, setInput] = useChatDraft(name);
  const attachments = useAttachmentDrafts(name);
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

  useEffect(() => {
    registerChat(sendWithDrafts, clearComposer, reportSpeaking);
  }, [registerChat, sendWithDrafts, clearComposer, reportSpeaking]);

  // Focus the composer whenever the chat becomes the visible surface: on mount,
  // and again when a logs/settings subpage closes (the pane stays mounted, so a
  // mount-time autofocus never refires). Skipped on mobile, where autofocus
  // would raise the keyboard on every open. A fullscreen and a panel Chat can
  // both be mounted; focus() is a no-op on the visibility-hidden one.
  const { pathname } = useLocation();
  useEffect(() => {
    if (isMobile || agentSubpage(pathname, name) !== null) return;
    textareaRef.current?.focus({ preventScroll: true });
  }, [isMobile, pathname, name]);

  // Every chat floats the composer over the message list; the messages reserve
  // its live height plus the gap at the bottom so the last one always clears it,
  // and the scroll-to-bottom button parks just above it.
  // Seed so a remounted chat (reopened from collapse) reserves the composer's space
  // on its first render, before the async measure lands; measuring the same value
  // then makes no re-pin, so bubbles don't snap. The cache holds the exact measured
  // height once the composer has mounted this session; a cold mount falls back to the
  // hardcoded baseline, which the real measurement overwrites.
  const composerVariant: ComposerVariant = isMobile
    ? "mobile"
    : fullscreen
      ? "fullscreen"
      : "panel";
  const setComposerBaseline = useLayout((s) => s.setComposerBaseline);
  const seedBaseline = () =>
    useLayout.getState().composerBaseline[composerVariant] ||
    COMPOSER_BASELINE_PX[composerVariant];
  const [composerInset, setComposerInset] = useState(seedBaseline);
  const [composerHeight, setComposerHeight] = useState(seedBaseline);
  // The inset tracks the composer's collapsed baseline only: a growing draft
  // expands the pill over the (masked, opaque-covered) list instead of shifting
  // it, so measurements while a draft exists are ignored (a cleared inset, 0,
  // always applies); send clears the draft and the next resize re-syncs. The
  // live height is tracked separately: its overhang beyond the baseline extends
  // the message list's scroll range, so the bubbles a tall draft covers stay
  // reachable by scrolling without the list ever shifting under the typist.
  const hasDraftRef = useRef(false);
  const inConversationRef = useRef(false);
  // The composer's height animates frame by frame during the conversation morph. Feeding
  // that into React would re-pad, re-mask and re-pin the whole message list every frame, so
  // the measurement is frozen for the morph and synced once when it settles.
  const morphingRef = useRef(false);
  const composerNodeRef = useRef<HTMLDivElement | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);
  // The last measured composer height, and the reservation frozen at the morph's first frame.
  const lastHeightRef = useRef(0);
  const frozenInsetRef = useRef(0);
  // True while the pill's height spring runs outside a morph; mid-animation measurements are
  // skipped and the settle resync writes the rest state.
  const heightAnimatingRef = useRef(false);
  useLayoutEffect(() => {
    // Attachment chips grow the pill exactly like typed text: both are drafts the
    // inset must ignore so the list never shifts under the composer.
    hasDraftRef.current = input.length > 0 || attachments.drafts.length > 0;
    inConversationRef.current = recordingMode === "conversation";
  });
  const composerGap = fullscreen
    ? COMPOSER_GAP_FULLSCREEN_PX
    : COMPOSER_GAP_PANEL_PX;
  const composerRef = useMeasuredSize(
    "height",
    useCallback(
      (height: number) => {
        lastHeightRef.current = height;
        const card = cardRef.current;
        // The list reserves the composer through these variables, so the reservation tracks
        // the morph frame by frame without a React render. While morphing the padding holds
        // still and a transform carries the same distance: changing padding inside the
        // receding (3D, promoted) layer re-rasterizes the whole chat every frame.
        if (morphingRef.current) {
          card?.style.setProperty(
            "--composer-shift",
            `${String(frozenInsetRef.current - height)}px`,
          );
          return;
        }
        // Mid-animation heights are transient (a cleared tall draft springing back down would
        // snap the list up to its overlay height); the settle resync writes the rest state.
        if (heightAnimatingRef.current) return;
        card?.style.setProperty("--composer-shift", "0px");
        setComposerHeight(height);
        // The var carries the same value as the state inset (baseline + gap) and obeys the
        // same draft rule: a growing draft expands the pill over the list, never pushes it.
        if (height === 0 || !hasDraftRef.current) {
          card?.style.setProperty(
            "--composer-inset",
            `${String(height + composerGap)}px`,
          );
          setComposerInset(height);
          // Cache only a real, draft-free baseline; unmount reports 0 and the morphed
          // conversation panel is a temporary height, and neither must overwrite the
          // seed the next remount reads.
          if (height > 0 && !inConversationRef.current)
            setComposerBaseline(composerVariant, height);
        }
      },
      [composerVariant, composerGap, setComposerBaseline],
    ),
  );

  // One resting-state write, shared by the morph settle and every height animation's end.
  // Padding and shift swap in one style write, so the handoff off the transform is unseen.
  const resyncInset = useCallback(() => {
    const node = composerNodeRef.current;
    if (!node) return;
    const height = node.getBoundingClientRect().height;
    if (height <= 0) return;
    const card = cardRef.current;
    card?.style.setProperty("--composer-shift", "0px");
    setComposerHeight(height);
    if (!hasDraftRef.current) {
      card?.style.setProperty(
        "--composer-inset",
        `${String(height + composerGap)}px`,
      );
      setComposerInset(height);
    }
  }, [composerGap]);

  // The composer's settle callback: the morph flag clears and the rest state lands in one step
  // (a settle outside a morph just re-syncs, which is a no-op).
  const onMorphSettled = useCallback(() => {
    morphingRef.current = false;
    resyncInset();
  }, [resyncInset]);

  const handleHeightAnimation = useCallback(
    (animating: boolean) => {
      heightAnimatingRef.current = animating;
      if (!animating && !morphingRef.current) resyncInset();
    },
    [resyncInset],
  );

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
  const inConversation = recordingMode === "conversation";
  // The morph starts on the conversation flip itself (either direction), freezing the inset
  // before motion's first frame lands; the composer reports only completion. A typing
  // animation therefore never trips the freeze.
  const prevConversationRef = useRef(inConversation);
  useLayoutEffect(() => {
    if (prevConversationRef.current === inConversation) return;
    prevConversationRef.current = inConversation;
    frozenInsetRef.current = lastHeightRef.current;
    morphingRef.current = true;
  }, [inConversation]);
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
      toast.error(`can't reach ${name} right now, message not sent`);
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
        <DropOverlay active={dragActive} agentName={name} />
        <AttachmentViewer agent={name} request={viewer} onClose={closeViewer} />
        <ChatHeaderActions
          fullscreen={fullscreen}
          receded={inConversation}
          onCollapse={onCollapse}
          agentName={name}
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
          agentName={name}
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
              agentName={name}
              notAuthenticated={notAuthenticated}
              voiceConfigured={voiceConfigured}
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
