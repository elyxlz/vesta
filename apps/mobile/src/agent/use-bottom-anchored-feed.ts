import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
} from "react-native";
import {
  FEED_BOTTOM_THRESHOLD,
  distanceFromSettledBottom,
} from "@/agent/bottom-anchored-feed-model";

export function useBottomAnchoredFeed<Item>(itemCount: number) {
  const listRef = useRef<FlatList<Item>>(null);
  const isNearBottom = useRef(true);
  // The content height as of the last size change. A growth's own position-hold adjustment
  // reports a scroll before the follow decision, so nearness is judged against the height the
  // reader last saw, and a burst of new lines never reads as the reader scrolling away.
  const settledContentHeight = useRef(0);
  const hasPositioned = useRef(false);
  const previousItemCount = useRef(itemCount);
  const positionFrame = useRef<number | null>(null);
  const revealFrame = useRef<number | null>(null);
  const [positioned, setPositioned] = useState(false);

  const cancelScheduledPosition = useCallback(() => {
    if (positionFrame.current !== null) {
      cancelAnimationFrame(positionFrame.current);
      positionFrame.current = null;
    }
    if (revealFrame.current !== null) {
      cancelAnimationFrame(revealFrame.current);
      revealFrame.current = null;
    }
  }, []);

  useEffect(() => cancelScheduledPosition, [cancelScheduledPosition]);

  const scrollToBottom = useCallback((revealAfterScroll: boolean) => {
    if (positionFrame.current !== null) {
      cancelAnimationFrame(positionFrame.current);
    }
    positionFrame.current = requestAnimationFrame(() => {
      positionFrame.current = null;
      listRef.current?.scrollToEnd({ animated: false });

      if (!revealAfterScroll) return;
      revealFrame.current = requestAnimationFrame(() => {
        revealFrame.current = null;
        setPositioned(true);
      });
    });
  }, []);

  const onContentSizeChange = useCallback(
    (_width: number, height: number) => {
      if (itemCount === 0) {
        cancelScheduledPosition();
        hasPositioned.current = false;
        isNearBottom.current = true;
        settledContentHeight.current = 0;
        previousItemCount.current = 0;
        setPositioned(false);
        return;
      }
      settledContentHeight.current = height;

      const isInitialPosition = itemCount > 0 && !hasPositioned.current;
      const appended = itemCount > previousItemCount.current;
      const shouldFollowNewItems = appended && isNearBottom.current;

      previousItemCount.current = itemCount;
      if (!isInitialPosition && !shouldFollowNewItems) return;

      if (isInitialPosition) hasPositioned.current = true;
      scrollToBottom(isInitialPosition);
    },
    [cancelScheduledPosition, itemCount, scrollToBottom],
  );

  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } =
        event.nativeEvent;
      const distanceFromBottom = distanceFromSettledBottom({
        settledContentHeight: settledContentHeight.current,
        contentHeight: contentSize.height,
        viewportHeight: layoutMeasurement.height,
        offset: contentOffset.y,
      });
      isNearBottom.current = distanceFromBottom <= FEED_BOTTOM_THRESHOLD;
    },
    [],
  );

  return {
    listRef,
    onContentSizeChange,
    onScroll,
    contentVisible: itemCount === 0 || positioned,
  };
}
