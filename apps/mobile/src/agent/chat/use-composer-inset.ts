import { useCallback, useRef } from "react";
import type { LayoutChangeEvent } from "react-native";
import {
  Easing,
  useAnimatedReaction,
  useDerivedValue,
  useSharedValue,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";
import { scheduleOnRN, scheduleOnUI } from "react-native-worklets";

const CHAT_COMPOSER_GAP = 6;
// The chat scroll view shifts its content for an inset change only from here (keyboard-controller's
// `isScrollAtEnd` on an inverted list); the transcript follows a reply slide exactly when it does.
const LIST_AT_END_OFFSET = 20;
const REPLY_SLIDE = {
  duration: 400,
  easing: Easing.bezier(0.32, 0.72, 0, 1).factory(),
};

// The composer's inset over the transcript, and the reply preview's slide. The inset is set, never
// tweened: the list compensates each inset delta against its last known scroll position, which lags
// an animated inset by a frame and loses a sliver per step. So a slide sets the final inset once,
// lets the list take its one shift, and translates the transcript back by what the preview has not
// yet grown, until both settle together.
export function useComposerInset(freeze: SharedValue<boolean>) {
  const composerInset = useSharedValue(0);
  const scrollOffset = useSharedValue(0);
  const replyHeight = useSharedValue(0);
  const replyTarget = useSharedValue(0);
  const listFollows = useSharedValue(false);
  const pendingGrow = useSharedValue<number | null>(null);
  const measuredHeight = useRef<number | null>(null);
  const insetRef = useRef(0);
  const targetRef = useRef(0);
  const slidingRef = useRef(false);

  const applyMeasured = useCallback(() => {
    if (measuredHeight.current === null) return;
    const inset = measuredHeight.current + CHAT_COMPOSER_GAP;
    if (Math.abs(insetRef.current - inset) < 0.5) return;
    insetRef.current = inset;
    composerInset.set(inset);
  }, [composerInset]);

  const handleComposerLayout = useCallback(
    (event: LayoutChangeEvent) => {
      measuredHeight.current = Math.max(event.nativeEvent.layout.height, 0);
      if (!slidingRef.current) applyMeasured();
    },
    [applyMeasured],
  );

  const settle = useCallback(() => {
    slidingRef.current = false;
    applyMeasured();
  }, [applyMeasured]);

  const startSlide = useCallback(
    (height: number) => {
      "worklet";
      replyTarget.set(height);
      replyHeight.set(
        withTiming(height, REPLY_SLIDE, (finished) => {
          if (finished) scheduleOnRN(settle);
        }),
      );
    },
    [replyHeight, replyTarget, settle],
  );

  // A larger inset reaches the list in two steps: the scroll view takes the
  // inset in the pass that runs this reaction, and moves its content in the
  // next frame's pass. The slide starts in that next frame, so the shift never
  // shows against an offset the list has not taken yet. A smaller inset moves
  // the content at once, so that slide starts with no wait.
  useAnimatedReaction(
    () => composerInset.get(),
    (inset, previous) => {
      const height = pendingGrow.get();
      if (height === null || previous === null || inset <= previous) return;
      pendingGrow.set(null);
      requestAnimationFrame(() => {
        startSlide(height);
      });
    },
  );

  const slideReplyTo = useCallback(
    (height: number) => {
      const delta = height - targetRef.current;
      if (Math.abs(delta) < 0.5) return;
      targetRef.current = height;
      // Before the composer's first layout there is nothing on screen to slide from.
      if (measuredHeight.current === null) {
        replyTarget.set(height);
        replyHeight.set(height);
        return;
      }
      slidingRef.current = true;
      insetRef.current += delta;
      const inset = insetRef.current;
      scheduleOnUI(() => {
        "worklet";
        listFollows.set(
          !freeze.get() && scrollOffset.get() <= LIST_AT_END_OFFSET,
        );
        // On a larger inset the reaction above starts the slide.
        pendingGrow.set(delta > 0 ? height : null);
        composerInset.set(inset);
        if (delta < 0) startSlide(height);
      });
    },
    [
      composerInset,
      freeze,
      listFollows,
      pendingGrow,
      replyHeight,
      replyTarget,
      scrollOffset,
      startSlide,
    ],
  );

  const transcriptShift = useDerivedValue(() =>
    listFollows.get() ? replyTarget.get() - replyHeight.get() : 0,
  );

  return {
    composerInset,
    scrollOffset,
    replyHeight,
    transcriptShift,
    handleComposerLayout,
    slideReplyTo,
  };
}
