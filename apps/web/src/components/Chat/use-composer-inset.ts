import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { useLayout, type ComposerVariant } from "@/stores/use-layout";
import { useMeasuredSize } from "@/hooks/use-measured-size";

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

// The floating composer's reservation over the message list: the measured inset and live
// height the list pads and overhangs by, frozen through the conversation morph.
export function useComposerInset({
  fullscreen,
  isMobile,
  hasDraft,
  inConversation,
}: {
  fullscreen: boolean | undefined;
  isMobile: boolean;
  hasDraft: boolean;
  inConversation: boolean;
}) {
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
    hasDraftRef.current = hasDraft;
    inConversationRef.current = inConversation;
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

  return {
    cardRef,
    composerRef,
    composerNodeRef,
    composerInset,
    composerHeight,
    composerGap,
    onMorphSettled,
    handleHeightAnimation,
  };
}
