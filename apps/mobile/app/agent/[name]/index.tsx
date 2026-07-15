import { useCallback, useMemo, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import PagerView, {
  type PageScrollStateChangedNativeEvent,
  type PagerViewOnPageScrollEvent,
  type PagerViewOnPageSelectedEvent,
} from "react-native-pager-view";
import Animated, { useEvent, useSharedValue } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AgentProvider } from "@/agent/AgentProvider";
import ChatPage from "@/agent/ChatPage";
import DashboardPage from "@/agent/DashboardPage";
import LogsPage from "@/agent/LogsPage";
import NotificationsPage from "@/agent/NotificationsPage";
import { getAgentPageKeys, type AgentPageKey } from "@/agent/pager-model";
import { AgentStackHeader } from "@/components/AgentHeader";
import {
  AgentPagerTabs,
  type AgentPagerTab,
} from "@/components/AgentPagerTabs";
import { usePreferences } from "@/preferences/PreferencesProvider";

const AnimatedPagerView = Animated.createAnimatedComponent(PagerView);
const PAGE_TABS = {
  chat: {
    key: "chat",
    label: "Chat",
    icon: "chatbubble-outline",
    selectedIcon: "chatbubble",
  },
  dashboard: {
    key: "dashboard",
    label: "Dashboard",
    icon: "grid-outline",
    selectedIcon: "grid",
  },
  notifications: {
    key: "notifications",
    label: "Notifications",
    icon: "notifications-outline",
    selectedIcon: "notifications",
  },
  logs: {
    key: "logs",
    label: "Logs",
    icon: "terminal-outline",
    selectedIcon: "terminal",
  },
} satisfies Record<AgentPageKey, AgentPagerTab>;

function AgentPages() {
  const insets = useSafeAreaInsets();
  const { showNotificationsPage, showLogsPage } = usePreferences();
  const pager = useRef<PagerView>(null);
  const pageProgress = useSharedValue(0);
  const [activePageKey, setActivePageKey] = useState<AgentPageKey>("chat");
  const [tabsInteractive, setTabsInteractive] = useState(false);
  const pages = useMemo(
    () => getAgentPageKeys({ showNotificationsPage, showLogsPage }),
    [showLogsPage, showNotificationsPage],
  );
  const pagerKey = pages.join(":");
  const selectedPageIndex = pages.indexOf(activePageKey);
  const activePage = selectedPageIndex >= 0 ? selectedPageIndex : 0;
  const tabs = useMemo(() => pages.map((page) => PAGE_TABS[page]), [pages]);
  const onPageScroll = useEvent<{ position: number; offset: number }>(
    (event) => {
      "worklet";
      if (event.eventName.endsWith("onPageScroll")) {
        pageProgress.value = event.position + event.offset;
      }
    },
    ["onPageScroll"],
  );

  const onPageScrollStateChanged = useCallback(
    (event: PageScrollStateChangedNativeEvent) =>
      setTabsInteractive(event.nativeEvent.pageScrollState !== "idle"),
    [],
  );

  const onPageSelected = useCallback(
    (event: PagerViewOnPageSelectedEvent) => {
      const position = event.nativeEvent.position;
      const page = pages[position];
      pageProgress.set(position);
      if (page) setActivePageKey(page);
    },
    [pageProgress, pages],
  );

  const selectPage = useCallback((page: number) => {
    pager.current?.setPage(page);
  }, []);

  return (
    <View style={styles.screen}>
      <AgentStackHeader />
      <AnimatedPagerView
        key={pagerKey}
        ref={pager}
        style={styles.pager}
        initialPage={activePage}
        orientation="horizontal"
        overdrag
        onPageScroll={
          onPageScroll as unknown as (event: PagerViewOnPageScrollEvent) => void
        }
        onPageScrollStateChanged={onPageScrollStateChanged}
        onPageSelected={onPageSelected}
      >
        {pages.map((page) => (
          <View key={page} collapsable={false} style={styles.page}>
            {page === "chat" ? <ChatPage /> : null}
            {page === "dashboard" ? <DashboardPage /> : null}
            {page === "notifications" ? <NotificationsPage /> : null}
            {page === "logs" ? <LogsPage /> : null}
          </View>
        ))}
      </AnimatedPagerView>
      <AgentPagerTabs
        activePage={activePage}
        top={insets.top + 52}
        progress={pageProgress}
        interactive={tabsInteractive}
        tabs={tabs}
        onSelect={selectPage}
      />
    </View>
  );
}

export default function AgentScreen() {
  return (
    <AgentProvider>
      <AgentPages />
    </AgentProvider>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  pager: { flex: 1 },
  page: { flex: 1 },
});
