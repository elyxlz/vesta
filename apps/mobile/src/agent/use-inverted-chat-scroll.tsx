import {
  forwardRef,
  useCallback,
  useRef,
  useState,
  type ComponentRef,
} from "react";
import {
  FlatList,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  type ScrollViewProps,
} from "react-native";
import {
  KeyboardChatScrollView,
  type KeyboardChatScrollViewProps,
} from "react-native-keyboard-controller";
import type { SharedValue } from "react-native-reanimated";
import {
  getLatestMessageOffset,
  isNearLatestMessage,
  shouldAnchorToLatest,
  type AnchorTrigger,
} from "@/agent/chat-scroll-model";

type ChatScrollViewRef = ComponentRef<typeof KeyboardChatScrollView>;
type ContentInsetChange = NonNullable<
  KeyboardChatScrollViewProps["onContentInsetChange"]
>;

const NativeChatScrollView = forwardRef<
  ChatScrollViewRef,
  ScrollViewProps & KeyboardChatScrollViewProps
>(({ inverted, ...props }, ref) => (
  <KeyboardChatScrollView
    ref={ref}
    automaticallyAdjustContentInsets={false}
    contentInsetAdjustmentBehavior="never"
    inverted={inverted}
    keyboardDismissMode="interactive"
    keyboardLiftBehavior="whenAtEnd"
    {...props}
  />
));
NativeChatScrollView.displayName = "NativeChatScrollView";

// `keyboardOffset` is the composer dock's own opened offset, so the list and
// the dock agree on how much of the keyboard's height the content must yield.
export function useInvertedChatScroll<Row>(
  extraContentPadding: SharedValue<number>,
  keyboardOffset: number,
) {
  const listRef = useRef<FlatList<Row>>(null);
  const isAtLatestRef = useRef(true);
  const anchoredRef = useRef(false);
  const hasContentRef = useRef(false);
  const latestOffsetRef = useRef(0);
  const [isAwayFromLatest, setIsAwayFromLatest] = useState(false);

  const attachList = useCallback((list: FlatList<Row> | null) => {
    listRef.current = list;
  }, []);

  const anchorToLatest = useCallback((trigger: AnchorTrigger) => {
    const anchor = shouldAnchorToLatest({
      platform: process.env.EXPO_OS,
      hasContent: hasContentRef.current,
      latestOffset: latestOffsetRef.current,
      atLatest: isAtLatestRef.current,
      anchored: anchoredRef.current,
      trigger,
    });
    if (!anchor) return;

    anchoredRef.current = true;
    listRef.current?.scrollToOffset({
      offset: latestOffsetRef.current,
      animated: false,
    });
  }, []);

  const handleContentInsetChange = useCallback<ContentInsetChange>(
    (insets) => {
      latestOffsetRef.current = getLatestMessageOffset(
        process.env.EXPO_OS,
        insets.top,
      );
      anchorToLatest("inset");
    },
    [anchorToLatest],
  );

  const handleContentSizeChange = useCallback(
    (_width: number, height: number) => {
      hasContentRef.current = height > 0;
      anchorToLatest("content");
    },
    [anchorToLatest],
  );

  const renderScrollComponent = useCallback(
    (props: ScrollViewProps) => (
      <NativeChatScrollView
        {...props}
        extraContentPadding={extraContentPadding}
        offset={keyboardOffset}
        onContentInsetChange={handleContentInsetChange}
      />
    ),
    [extraContentPadding, handleContentInsetChange, keyboardOffset],
  );

  const handleScroll = useCallback(
    ({ nativeEvent }: NativeSyntheticEvent<NativeScrollEvent>) => {
      const isAtLatest = isNearLatestMessage(
        nativeEvent.contentOffset.y,
        latestOffsetRef.current,
      );
      if (isAtLatestRef.current === isAtLatest) return;

      isAtLatestRef.current = isAtLatest;
      setIsAwayFromLatest(!isAtLatest);
    },
    [],
  );

  const scrollToLatest = useCallback(() => {
    isAtLatestRef.current = true;
    setIsAwayFromLatest(false);
    listRef.current?.scrollToOffset({
      offset: latestOffsetRef.current,
      animated: true,
    });
  }, []);

  return {
    attachList,
    handleContentSizeChange,
    handleScroll,
    isAwayFromLatest,
    renderScrollComponent,
    scrollToLatest,
  };
}
