import { useCallback, useEffect, useRef, useState } from "react";
import type {
  FlatList,
  NativeScrollEvent,
  NativeSyntheticEvent,
} from "react-native";

const BOTTOM_THRESHOLD = 32;

export function useBottomAnchoredFeed<Item>(itemCount: number) {
  const listRef = useRef<FlatList<Item>>(null);
  const isNearBottom = useRef(true);
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

  const onContentSizeChange = useCallback(() => {
    if (itemCount === 0) {
      cancelScheduledPosition();
      hasPositioned.current = false;
      isNearBottom.current = true;
      previousItemCount.current = 0;
      setPositioned(false);
      return;
    }

    const isInitialPosition = itemCount > 0 && !hasPositioned.current;
    const appended = itemCount > previousItemCount.current;
    const shouldFollowNewItems = appended && isNearBottom.current;

    previousItemCount.current = itemCount;
    if (!isInitialPosition && !shouldFollowNewItems) return;

    if (isInitialPosition) hasPositioned.current = true;
    scrollToBottom(isInitialPosition);
  }, [cancelScheduledPosition, itemCount, scrollToBottom]);

  const onScroll = useCallback(
    (event: NativeSyntheticEvent<NativeScrollEvent>) => {
      const { contentOffset, contentSize, layoutMeasurement } =
        event.nativeEvent;
      const distanceFromBottom =
        contentSize.height - layoutMeasurement.height - contentOffset.y;
      isNearBottom.current = distanceFromBottom <= BOTTOM_THRESHOLD;
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
