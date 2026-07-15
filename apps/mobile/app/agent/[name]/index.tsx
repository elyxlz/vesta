import { useCallback, useRef, useState } from "react";
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
import { AgentStackHeader } from "@/components/AgentHeader";
import { AgentPagerTabs } from "@/components/AgentPagerTabs";

const AnimatedPagerView = Animated.createAnimatedComponent(PagerView);

function AgentPages() {
  const insets = useSafeAreaInsets();
  const pager = useRef<PagerView>(null);
  const pageProgress = useSharedValue(0);
  const [activePage, setActivePage] = useState(0);
  const [tabsInteractive, setTabsInteractive] = useState(false);
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

  const onPageSelected = useCallback((event: PagerViewOnPageSelectedEvent) => {
    setActivePage(event.nativeEvent.position);
  }, []);

  const selectPage = useCallback((page: number) => {
    pager.current?.setPage(page);
  }, []);

  return (
    <View style={styles.screen}>
      <AgentStackHeader />
      <AnimatedPagerView
        ref={pager}
        style={styles.pager}
        initialPage={0}
        orientation="horizontal"
        overdrag
        onPageScroll={
          onPageScroll as unknown as (event: PagerViewOnPageScrollEvent) => void
        }
        onPageScrollStateChanged={onPageScrollStateChanged}
        onPageSelected={onPageSelected}
      >
        <View key="chat" collapsable={false} style={styles.page}>
          <ChatPage />
        </View>
        <View key="dashboard" collapsable={false} style={styles.page}>
          <DashboardPage />
        </View>
      </AnimatedPagerView>
      <AgentPagerTabs
        activePage={activePage}
        top={insets.top + 52}
        progress={pageProgress}
        interactive={tabsInteractive}
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
