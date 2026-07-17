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
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  getLatestMessageOffset,
  isNearLatestMessage,
} from "@/agent/chat-scroll-model";

const COMPOSER_MARGIN = 8;

type ChatScrollViewRef = ComponentRef<typeof KeyboardChatScrollView>;
type ContentInsetChange = NonNullable<
  KeyboardChatScrollViewProps["onContentInsetChange"]
>;

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

export function useInvertedChatScroll<Row>(
  extraContentPadding: SharedValue<number>,
) {
  const listRef = useRef<FlatList<Row>>(null);
  const isAtLatestRef = useRef(true);
  const latestOffsetRef = useRef(0);
  const [isAwayFromLatest, setIsAwayFromLatest] = useState(false);

  const attachList = useCallback((list: FlatList<Row> | null) => {
    listRef.current = list;
  }, []);

  const handleContentInsetChange = useCallback<ContentInsetChange>(
    (insets) => {
      latestOffsetRef.current = getLatestMessageOffset(
        process.env.EXPO_OS,
        insets.top,
      );
    },
    [],
  );

  const renderScrollComponent = useCallback(
    (props: ScrollViewProps) => (
      <NativeChatScrollView
        {...props}
        extraContentPadding={extraContentPadding}
        onContentInsetChange={handleContentInsetChange}
      />
    ),
    [extraContentPadding, handleContentInsetChange],
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
    handleScroll,
    isAwayFromLatest,
    renderScrollComponent,
    scrollToLatest,
  };
}
