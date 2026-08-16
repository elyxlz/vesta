import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, View, type GestureResponderEvent } from "react-native";
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
  withTiming,
} from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useAgent } from "@/agent/AgentProvider";
import ChatPage from "@/agent/ChatPage";
import DashboardPage from "@/agent/DashboardPage";
import LogsPage from "@/agent/LogsPage";
import NotificationsPage from "@/agent/NotificationsPage";
import { getAgentPageKeys, type AgentPageKey } from "@/agent/pager-model";
import { AgentStackHeader } from "@/components/AgentHeader";
import { useAgentHolds } from "@/holds/AgentHoldsProvider";
import { agentHoldKey } from "@/holds/keyed-hold";
import { useSession } from "@/session/SessionProvider";
import { connectionKeyOf } from "@/session/session-model";
import {
  AgentPagerTabs,
  type AgentPagerTab,
} from "@/components/AgentPagerTabs";
import { HeaderFade } from "@/components/header-fade";
import { usePreferences } from "@/preferences/PreferencesProvider";

const AnimatedPagerView = Animated.createAnimatedComponent(PagerView);
const TAB_HIDE_DELAY_MS = 50;
const INITIAL_TAB_HINT_DELAY_MS = 1_000;
const TAB_ANIMATION_DURATION_MS = 220;
const TAB_BOTTOM_MARGIN = 24;
const TAP_MAX_TRAVEL = 8;
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
  const { name } = useAgent();
  const { connection } = useSession();
  const holds = useAgentHolds();
  const holdKey = agentHoldKey(name, connectionKeyOf(connection) ?? "");
  const pager = useRef<PagerView>(null);
  const tabVisibility = useSharedValue(1);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const tabInteractionTimer = useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const tabTransitionId = useRef(0);
  const pageTouchStart = useRef<{ x: number; y: number } | null>(null);
  const pages = useMemo(
    () => getAgentPageKeys({ showNotificationsPage, showLogsPage }),
    [showLogsPage, showNotificationsPage],
  );
  // Reopen on the page the user last used for this agent (held above navigation), falling back to
  // chat when the held page is hidden by preferences.
  const [activePageKey, setActivePageKey] = useState<AgentPageKey>(() => {
    const held = holds.page.read(holdKey);
    return held !== null && pages.includes(held) ? held : "chat";
  });
  // Non-chat pages mount on their first visit (or as a drag approaches them) and stay mounted, so
  // the dashboard webview and the log stream cost nothing until seen, then keep their state.
  const [visitedPages, setVisitedPages] = useState<readonly AgentPageKey[]>(
    () => (activePageKey === "chat" ? ["chat"] : ["chat", activePageKey]),
  );
  const hapticPageKey = useRef<AgentPageKey>(activePageKey);
  const [tabsVisible, setTabsVisible] = useState(true);
  const [tabsInteractive, setTabsInteractive] = useState(true);
  const pagerKey = pages.join(":");
  const selectedPageIndex = pages.indexOf(activePageKey);
  const activePage = selectedPageIndex >= 0 ? selectedPageIndex : 0;
  const pageProgress = useSharedValue(activePage);
  const tabs = useMemo(() => pages.map((page) => PAGE_TABS[page]), [pages]);
  const markVisited = useCallback((keys: AgentPageKey[]) => {
    setVisitedPages((current) => {
      const missing = keys.filter((page) => !current.includes(page));
      return missing.length > 0 ? [...current, ...missing] : current;
    });
  }, []);
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

  const clearTabInteractionTimer = useCallback(() => {
    if (!tabInteractionTimer.current) return;
    clearTimeout(tabInteractionTimer.current);
    tabInteractionTimer.current = null;
  }, []);

  const animateTabsIn = useCallback(() => {
    tabVisibility.set(
      withTiming(1, {
        duration: TAB_ANIMATION_DURATION_MS,
        easing: Easing.out(Easing.cubic),
      }),
    );
  }, [tabVisibility]);

  const showTabs = useCallback(() => {
    clearHideTimer();
    clearTabInteractionTimer();
    tabTransitionId.current += 1;
    setTabsVisible(true);
    setTabsInteractive(true);
    animateTabsIn();
  }, [animateTabsIn, clearHideTimer, clearTabInteractionTimer]);

  const disableTabs = useCallback((transitionId: number) => {
    if (transitionId !== tabTransitionId.current) return;
    setTabsInteractive(false);
  }, []);

  const animateTabsOut = useCallback(() => {
    clearTabInteractionTimer();
    const transitionId = ++tabTransitionId.current;
    setTabsVisible(false);
    tabVisibility.set(
      withTiming(
        0,
        {
          duration: TAB_ANIMATION_DURATION_MS,
          easing: Easing.in(Easing.cubic),
        },
      ),
    );
    tabInteractionTimer.current = setTimeout(() => {
      tabInteractionTimer.current = null;
      disableTabs(transitionId);
    }, TAB_ANIMATION_DURATION_MS);
  }, [clearTabInteractionTimer, disableTabs, tabVisibility]);

  const hideTabsImmediately = useCallback(() => {
    clearHideTimer();
    animateTabsOut();
  }, [animateTabsOut, clearHideTimer]);

  const onPageTouchStart = useCallback((event: GestureResponderEvent) => {
    pageTouchStart.current = {
      x: event.nativeEvent.pageX,
      y: event.nativeEvent.pageY,
    };
  }, []);

  const onPageTouchEnd = useCallback(
    (event: GestureResponderEvent) => {
      const start = pageTouchStart.current;
      pageTouchStart.current = null;
      if (
        start &&
        Math.abs(event.nativeEvent.pageX - start.x) <= TAP_MAX_TRAVEL &&
        Math.abs(event.nativeEvent.pageY - start.y) <= TAP_MAX_TRAVEL
      ) {
        hideTabsImmediately();
      }
    },
    [hideTabsImmediately],
  );

  const hideTabs = useCallback(() => {
    clearHideTimer();
    hideTimer.current = setTimeout(() => {
      hideTimer.current = null;
      animateTabsOut();
    }, TAB_HIDE_DELAY_MS);
  }, [animateTabsOut, clearHideTimer]);

  useEffect(() => {
    hideTimer.current = setTimeout(() => {
      hideTimer.current = null;
      animateTabsOut();
    }, INITIAL_TAB_HINT_DELAY_MS);

    return () => {
      clearHideTimer();
      clearTabInteractionTimer();
      cancelAnimation(tabVisibility);
    };
  }, [
    animateTabsOut,
    clearHideTimer,
    clearTabInteractionTimer,
    tabVisibility,
  ]);

  const onPageScrollStateChanged = useCallback(
    (event: PageScrollStateChangedNativeEvent) => {
      const state = event.nativeEvent.pageScrollState;
      if (state === "dragging") {
        void KeyboardController.dismiss().catch(() => undefined);
        const index = pages.indexOf(activePageKey);
        markVisited(
          [pages[index - 1], pages[index + 1]].filter(
            (page): page is AgentPageKey => page !== undefined,
          ),
        );
      }
      if (state === "idle") {
        hideTabs();
      } else {
        showTabs();
      }
    },
    [activePageKey, hideTabs, markVisited, pages, showTabs],
  );

  const onPageSelected = useCallback(
    (event: PagerViewOnPageSelectedEvent) => {
      const position = event.nativeEvent.position;
      const page = pages[position];
      pageProgress.set(position);
      if (page) {
        setActivePageKey(page);
        markVisited([page]);
        holds.page.persist(holdKey, page);
        if (page !== hapticPageKey.current) {
          hapticPageKey.current = page;
          void Haptics.selectionAsync().catch(() => undefined);
        }
      }
    },
    [holdKey, holds, markVisited, pageProgress, pages],
  );

  const selectPage = useCallback(
    (page: number) => {
      const target = pages[page];
      if (target) markVisited([target]);
      if (target && target !== hapticPageKey.current) {
        hapticPageKey.current = target;
        void Haptics.selectionAsync().catch(() => undefined);
      }
      showTabs();
      pager.current?.setPage(page);
    },
    [markVisited, pages, showTabs],
  );

  return (
    <View style={styles.screen}>
      <AgentStackHeader />
      <AnimatedPagerView
        key={pagerKey}
        ref={pager}
        style={styles.pager}
        initialPage={activePage}
        // Keep every page's native view attached on Android; the default ViewPager2 limit detaches
        // pages more than one position away, which blanks the webview and drops list state.
        offscreenPageLimit={Math.max(pages.length - 1, 1)}
        orientation="horizontal"
        overdrag
        onTouchStart={onPageTouchStart}
        onTouchEnd={onPageTouchEnd}
        onTouchCancel={() => {
          pageTouchStart.current = null;
        }}
        onPageScroll={
          onPageScroll as unknown as (event: PagerViewOnPageScrollEvent) => void
        }
        onPageScrollStateChanged={onPageScrollStateChanged}
        onPageSelected={onPageSelected}
      >
        {pages.map((page) => (
          <View key={page} collapsable={false} style={styles.page}>
            {visitedPages.includes(page) ? (
              page === "chat" ? (
                <ChatPage />
              ) : page === "dashboard" ? (
                <DashboardPage />
              ) : page === "notifications" ? (
                <NotificationsPage />
              ) : (
                <LogsPage />
              )
            ) : null}
          </View>
        ))}
      </AnimatedPagerView>
      <HeaderFade />
      <AgentPagerTabs
        activePage={activePage}
        bottom={insets.bottom + TAB_BOTTOM_MARGIN}
        progress={pageProgress}
        visibility={tabVisibility}
        visible={tabsVisible}
        interactive={tabsInteractive}
        tabs={tabs}
        onSelect={selectPage}
      />
    </View>
  );
}

export default function AgentScreen() {
  return <AgentPages />;
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  pager: { flex: 1 },
  page: { flex: 1 },
});
