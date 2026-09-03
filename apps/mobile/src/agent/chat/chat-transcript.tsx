import { memo, useCallback, useMemo, type ReactElement } from "react";
import {
  FlatList,
  StyleSheet,
  View,
  type ListRenderItem,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  type ScrollViewProps,
} from "react-native";
import Reanimated, {
  useAnimatedStyle,
  type SharedValue,
} from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";
import type { ChatAttachment, InputMethod } from "@vesta/core";
import type { OpenViewerRequest } from "@/agent/chat/attachment-content";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ChatLoadingSkeleton } from "@/components/chat-loading-skeleton";
import { LoadingSpinner } from "@/components/loading-spinner";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import type { ChatRow } from "@/agent/chat-list-model";
import {
  ChatDateHeader,
  ChatEvent,
  TypingIndicator,
} from "@/agent/chat/chat-event";

// Android's translucent 3-button navigation bar shows list content through
// it, so a background veil covers the bar zone; iOS keeps content visible
// under its hairline home indicator.
const NAV_BAR_VEIL = process.env.EXPO_OS === "android";
const NAV_BAR_VEIL_FADE = 12;

const keyExtractor = (row: ChatRow) => row.key;

export const ChatTranscript = memo(function ChatTranscript({
  rows,
  agentName,
  canSpeak,
  historyLoaded,
  loadingMore,
  composerInset,
  attachList,
  onScroll,
  onContentSizeChange,
  renderScrollComponent,
  onLoadEarlier,
  onReply,
  onEditAndResend,
  onReadAloud,
  onRetry,
  onOpenAttachment,
}: {
  rows: ChatRow[];
  agentName: string;
  canSpeak: boolean;
  historyLoaded: boolean;
  loadingMore: boolean;
  composerInset: SharedValue<number>;
  attachList: (list: FlatList<ChatRow> | null) => void;
  onScroll: (event: NativeSyntheticEvent<NativeScrollEvent>) => void;
  onContentSizeChange: (width: number, height: number) => void;
  renderScrollComponent: (
    props: ScrollViewProps,
  ) => ReactElement<ScrollViewProps>;
  onLoadEarlier: () => void;
  onReply: (text: string, user: boolean) => void;
  onEditAndResend: (text: string) => void;
  onReadAloud: (text: string) => void;
  onRetry: (
    intentId: string,
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  onOpenAttachment: (request: OpenViewerRequest) => void;
}) {
  const insets = useSafeAreaInsets();
  const { colors } = usePreferences();
  const empty = rows.length === 0;
  const contentContainerStyle = useMemo(
    () => [
      styles.listContent,
      {
        paddingBottom: insets.top + 104,
        flexGrow: empty ? 1 : undefined,
      },
    ],
    [insets.top, empty],
  );
  const loadingOverlayInsetStyle = useAnimatedStyle(() => ({
    paddingBottom: composerInset.value,
  }));
  const renderChatEvent = useCallback<ListRenderItem<ChatRow>>(
    ({ item }) =>
      item.kind === "typing" ? (
        <TypingIndicator
          agentName={agentName}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
        />
      ) : item.kind === "date" ? (
        <ChatDateHeader timestamp={item.timestamp} />
      ) : (
        <ChatEvent
          event={item.event}
          agentName={agentName}
          startsNewBubbleGroup={item.startsNewBubbleGroup}
          endsBubbleGroup={item.endsBubbleGroup}
          canSpeak={canSpeak}
          onReply={onReply}
          onEditAndResend={onEditAndResend}
          onReadAloud={onReadAloud}
          onRetry={onRetry}
          onOpenAttachment={onOpenAttachment}
        />
      ),
    [
      agentName,
      canSpeak,
      onEditAndResend,
      onOpenAttachment,
      onReadAloud,
      onReply,
      onRetry,
    ],
  );

  return (
    <>
      <FlatList
        ref={attachList}
        data={rows}
        inverted
        keyExtractor={keyExtractor}
        renderItem={renderChatEvent}
        contentContainerStyle={contentContainerStyle}
        keyboardShouldPersistTaps="handled"
        scrollEnabled={historyLoaded || rows.length > 0}
        renderScrollComponent={renderScrollComponent}
        onScroll={onScroll}
        onContentSizeChange={onContentSizeChange}
        scrollEventThrottle={16}
        onEndReached={onLoadEarlier}
        onEndReachedThreshold={0.1}
        ListFooterComponent={
          loadingMore ? (
            <View style={styles.loadingMore}>
              <LoadingSpinner color={colors.interactive} />
            </View>
          ) : null
        }
        ListEmptyComponent={
          historyLoaded ? (
            <View style={styles.empty}>
              <Text
                family="heading"
                style={[styles.emptyTitle, { color: colors.text }]}
              >
                Start a conversation
              </Text>
              <Text
                style={[styles.emptyDetail, { color: colors.secondaryText }]}
              >
                Tell {agentName} what you want to accomplish.
              </Text>
            </View>
          ) : null
        }
      />
      {!historyLoaded && rows.length === 0 ? (
        <Reanimated.View
          pointerEvents="none"
          style={[styles.loadingOverlay, loadingOverlayInsetStyle]}
        >
          <ChatLoadingSkeleton />
        </Reanimated.View>
      ) : null}
      {NAV_BAR_VEIL && insets.bottom > 0 ? (
        <LinearGradient
          pointerEvents="none"
          colors={[
            `${colors.background}00`,
            colors.background,
            colors.background,
          ]}
          locations={[
            0,
            NAV_BAR_VEIL_FADE / (insets.bottom + NAV_BAR_VEIL_FADE),
            1,
          ]}
          style={[
            styles.navBarVeil,
            { height: insets.bottom + NAV_BAR_VEIL_FADE },
          ]}
        />
      ) : null}
    </>
  );
});

const styles = StyleSheet.create({
  listContent: { paddingHorizontal: 12 },
  navBarVeil: {
    position: "absolute",
    zIndex: 1,
    right: 0,
    bottom: 0,
    left: 0,
  },
  loadingOverlay: {
    position: "absolute",
    zIndex: 1,
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    paddingHorizontal: 12,
  },
  loadingMore: { height: 44, alignItems: "center", justifyContent: "center" },
  empty: {
    minHeight: 300,
    justifyContent: "center",
    alignItems: "center",
    gap: 7,
    padding: 30,
  },
  emptyTitle: { fontSize: 21, fontWeight: "500" },
  emptyDetail: { fontSize: 14, textAlign: "center" },
});
