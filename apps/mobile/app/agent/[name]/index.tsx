import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View } from "react-native";
import PagerView, {
  type PageScrollStateChangedNativeEvent,
  type PagerViewOnPageScrollEvent,
  type PagerViewOnPageSelectedEvent,
} from "react-native-pager-view";
import * as Haptics from "expo-haptics";
import { KeyboardController } from "react-native-keyboard-controller";
import Animated, {
  Easing,
  cancelAnimation,
  useEvent,
  useSharedValue,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { scheduleOnRN } from "react-native-worklets";
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
const TAB_HIDE_DELAY_MS = 100;
const TAB_HIDE_DURATION_MS = 220;
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
  const tabVisibility = useSharedValue(0);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hapticPageKey = useRef<AgentPageKey>("chat");
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

  const clearHideTimer = useCallback(() => {
    if (!hideTimer.current) return;
    clearTimeout(hideTimer.current);
    hideTimer.current = null;
  }, []);

  const showTabs = useCallback(() => {
    clearHideTimer();
    setTabsInteractive(true);
    tabVisibility.set(
      withSpring(1, {
        damping: 22,
        stiffness: 260,
        mass: 0.8,
        overshootClamping: true,
      }),
    );
  }, [clearHideTimer, tabVisibility]);

  const unmountTabSurface = useCallback(() => {
    setTabsInteractive(false);
  }, []);

  const hideTabs = useCallback(() => {
    clearHideTimer();
    hideTimer.current = setTimeout(() => {
      hideTimer.current = null;
      tabVisibility.set(
        withTiming(
          0,
          {
            duration: TAB_HIDE_DURATION_MS,
            easing: Easing.in(Easing.cubic),
          },
          (finished) => {
            if (finished) scheduleOnRN(unmountTabSurface);
          },
        ),
      );
    }, TAB_HIDE_DELAY_MS);
  }, [clearHideTimer, tabVisibility, unmountTabSurface]);

  useEffect(
    () => () => {
      clearHideTimer();
      cancelAnimation(tabVisibility);
    },
    [clearHideTimer, tabVisibility],
  );

  const onPageScrollStateChanged = useCallback(
    (event: PageScrollStateChangedNativeEvent) => {
      const state = event.nativeEvent.pageScrollState;
      if (state === "dragging") {
        void KeyboardController.dismiss().catch(() => undefined);
      }
      if (state === "idle") {
        hideTabs();
      } else {
        showTabs();
      }
    },
    [hideTabs, showTabs],
  );

  const onPageSelected = useCallback(
    (event: PagerViewOnPageSelectedEvent) => {
      const position = event.nativeEvent.position;
      const page = pages[position];
      pageProgress.set(position);
      if (page) {
        setActivePageKey(page);
        if (page !== hapticPageKey.current) {
          hapticPageKey.current = page;
          void Haptics.selectionAsync().catch(() => undefined);
        }
      }
    },
    [pageProgress, pages],
  );

  const selectPage = useCallback(
    (page: number) => {
      const target = pages[page];
      if (target && target !== hapticPageKey.current) {
        hapticPageKey.current = target;
        void Haptics.selectionAsync().catch(() => undefined);
      }
      showTabs();
      pager.current?.setPage(page);
    },
    [pages, showTabs],
  );

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
        bottom={insets.bottom + 40}
        progress={pageProgress}
        visibility={tabVisibility}
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
