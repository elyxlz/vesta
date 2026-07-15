import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
} from "react";
import {
  AccessibilityInfo,
  Animated,
  Easing,
  FlatList,
  Pressable,
  StyleSheet,
  View,
  useWindowDimensions,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Stack, useFocusEffect, useRouter } from "expo-router";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";
import type { AgentInfo } from "@/api/types";
import { AgentOrb } from "@/components/AgentOrb";
import { AgentStatusBadge } from "@/components/AgentStatus";
import { BootTransitionTarget } from "@/components/BootTransition";
import { Screen } from "@/components/layout/Screen";
import { EmptyState } from "@/components/ui/States";
import { Text } from "@/components/ui/Typography";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import { readLastUsedAgent } from "@/storage/recent-agent";

interface RestoreRequest {
  id: number;
  name: string;
}

const HOME_AGENT_ORB_SIZE = 144;
const PAGE_DOT_SIZE = 7;
const PAGE_DOT_ACTIVE_WIDTH = 20;

export default function HomeScreen() {
  const router = useRouter();
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const { status, agents, agentsReady } = useSession();
  const { colors } = usePreferences();
  const carouselRef = useRef<FlatList<AgentInfo>>(null);
  const hapticPageIndex = useRef(0);
  const [scrollX] = useState(() => new Animated.Value(0));
  const restoreRequestId = useRef(0);
  const restoredRequestId = useRef(0);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [initialAgentReady, setInitialAgentReady] = useState(false);
  const [restoreRequest, setRestoreRequest] = useState<RestoreRequest | null>(
    null,
  );
  const activeIndex = Math.min(selectedIndex, Math.max(agents.length - 1, 0));

  useFocusEffect(
    useCallback(() => {
      let active = true;

      void readLastUsedAgent().then((name) => {
        if (!active) return;
        if (!name) {
          setInitialAgentReady(true);
          return;
        }
        restoreRequestId.current += 1;
        setRestoreRequest({ id: restoreRequestId.current, name });
      });

      return () => {
        active = false;
      };
    }, []),
  );

  useEffect(() => {
    if (
      !restoreRequest ||
      agents.length === 0 ||
      restoredRequestId.current === restoreRequest.id
    ) {
      return;
    }

    restoredRequestId.current = restoreRequest.id;
    const index = agents.findIndex(
      (agent) => agent.name === restoreRequest.name,
    );
    if (index < 0) {
      const frame = requestAnimationFrame(() => setInitialAgentReady(true));
      return () => cancelAnimationFrame(frame);
    }

    const frame = requestAnimationFrame(() => {
      setSelectedIndex(index);
      hapticPageIndex.current = index;
      scrollX.setValue(width * index);
      carouselRef.current?.scrollToIndex({ index, animated: false });
      setInitialAgentReady(true);
    });

    return () => cancelAnimationFrame(frame);
  }, [agents, restoreRequest, scrollX, width]);

  if (status === "booting" || (status === "connected" && !agentsReady)) {
    return <HomeSkeleton />;
  }

  const openAgent = (agent: AgentInfo) => {
    router.push({
      pathname: "/agent/[name]",
      params: { name: agent.name },
    });
  };

  const updateSelectedAgent = (
    event: NativeSyntheticEvent<NativeScrollEvent>,
  ) => {
    const nextIndex = Math.round(event.nativeEvent.contentOffset.x / width);
    setSelectedIndex(nextIndex);
  };

  const prepareSelectedAgent = (
    event: NativeSyntheticEvent<NativeScrollEvent>,
  ) => {
    const destinationX =
      event.nativeEvent.targetContentOffset?.x ??
      event.nativeEvent.contentOffset.x;
    const nextIndex = Math.round(destinationX / width);
    if (nextIndex !== hapticPageIndex.current) {
      hapticPageIndex.current = nextIndex;
      void Haptics.selectionAsync().catch(() => undefined);
    }
  };

  return (
    <Screen scroll={false} contentStyle={styles.screen}>
      <Stack.Screen
        options={{
          headerLargeTitle: false,
          headerTransparent: true,
          headerStyle: { backgroundColor: "transparent" },
          headerShadowVisible: false,
          headerBackVisible: false,
          headerTitle: () => <HomeWordmark />,
          unstable_headerLeftItems: () => [
            {
              type: "button",
              label: "Settings",
              accessibilityLabel: "Settings",
              icon: { type: "sfSymbol", name: "gearshape" },
              tintColor: colors.text,
              identifier: "home-settings",
              onPress: () => router.push("/settings"),
            },
          ],
          unstable_headerRightItems: () => [
            {
              type: "button",
              label: "Create agent",
              accessibilityLabel: "Create agent",
              icon: { type: "sfSymbol", name: "plus" },
              tintColor: colors.text,
              identifier: "home-create-agent",
              onPress: () => router.push("/new-agent"),
            },
          ],
          headerLeft: () => (
            <HomeHeaderButton
              accessibilityLabel="Settings"
              icon="settings-outline"
              iconSize={21}
              onPress={() => router.push("/settings")}
            />
          ),
          headerRight: () => (
            <HomeHeaderButton
              accessibilityLabel="Create agent"
              icon="add"
              iconSize={26}
              onPress={() => router.push("/new-agent")}
            />
          ),
        }}
      />

      {agents.length === 0 ? (
        <View style={styles.empty}>
          <EmptyState
            title="Create your first agent"
            detail="Give Vesta a name, choose a model, and shape how your new agent approaches the world."
            action={{
              label: "Create agent",
              onPress: () => router.push("/new-agent"),
            }}
          />
        </View>
      ) : (
        <>
          <Animated.FlatList
            ref={carouselRef}
            data={agents}
            style={styles.carousel}
            horizontal
            pagingEnabled
            showsHorizontalScrollIndicator={false}
            bounces
            alwaysBounceHorizontal
            overScrollMode="always"
            decelerationRate="fast"
            disableIntervalMomentum
            keyExtractor={(agent) => agent.name}
            getItemLayout={(_, index) => ({
              length: width,
              offset: width * index,
              index,
            })}
            onScroll={Animated.event(
              [{ nativeEvent: { contentOffset: { x: scrollX } } }],
              { useNativeDriver: true },
            )}
            scrollEventThrottle={16}
            onScrollEndDrag={prepareSelectedAgent}
            onMomentumScrollEnd={updateSelectedAgent}
            renderItem={({ item, index }) => (
              <AgentCarouselItem
                agent={item}
                bootTarget={initialAgentReady && index === activeIndex}
                width={width}
                onOpen={() => openAgent(item)}
              />
            )}
          />
          <View
            accessible
            accessibilityLabel={`Agent ${activeIndex + 1} of ${agents.length}`}
            pointerEvents="none"
            style={[styles.indicators, { bottom: Math.max(insets.bottom, 16) }]}
          >
            {agents.map((agent, index) => (
              <View key={agent.name} style={styles.indicatorSlot}>
                <View
                  style={[
                    styles.indicatorDot,
                    { backgroundColor: colors.border },
                  ]}
                />
                <Animated.View
                  style={[
                    styles.indicatorActive,
                    {
                      backgroundColor: colors.accent,
                      opacity: scrollX.interpolate({
                        inputRange: [
                          (index - 1) * width,
                          index * width,
                          (index + 1) * width,
                        ],
                        outputRange: [0, 1, 0],
                        extrapolate: "clamp",
                      }),
                      transform: [
                        {
                          scaleX: scrollX.interpolate({
                            inputRange: [
                              (index - 1) * width,
                              index * width,
                              (index + 1) * width,
                            ],
                            outputRange: [
                              PAGE_DOT_SIZE / PAGE_DOT_ACTIVE_WIDTH,
                              1,
                              PAGE_DOT_SIZE / PAGE_DOT_ACTIVE_WIDTH,
                            ],
                            extrapolate: "clamp",
                          }),
                        },
                      ],
                    },
                  ]}
                />
              </View>
            ))}
          </View>
        </>
      )}
    </Screen>
  );
}

function AgentCarouselItem({
  agent,
  bootTarget,
  onOpen,
  width,
}: {
  agent: AgentInfo;
  bootTarget: boolean;
  onOpen: () => void;
  width: number;
}) {
  const { colors } = usePreferences();
  const [orbScale] = useState(() => new Animated.Value(1));
  const [orbReveal] = useState(() => new Animated.Value(0));

  useEffect(() => {
    const reveal = Animated.timing(orbReveal, {
      toValue: 1,
      duration: 320,
      easing: Easing.out(Easing.cubic),
      useNativeDriver: true,
    });
    reveal.start();
    return () => reveal.stop();
  }, [orbReveal]);

  const animateOrb = (toValue: number, released: boolean) => {
    orbScale.stopAnimation();
    Animated.spring(orbScale, {
      toValue,
      stiffness: released ? 320 : 420,
      damping: released ? 18 : 30,
      mass: 0.65,
      useNativeDriver: true,
    }).start();
  };

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Open ${agent.name}`}
      onPress={() => {
        void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(
          () => undefined,
        );
        onOpen();
      }}
      onPressIn={() => animateOrb(0.93, false)}
      onPressOut={() => animateOrb(1, true)}
      style={[styles.agentPage, { width }]}
    >
      <Animated.View
        style={[styles.orbHandoff, { transform: [{ scale: orbScale }] }]}
      >
        <Animated.View
          style={[StyleSheet.absoluteFill, { opacity: orbReveal }]}
        >
          <BootTransitionTarget
            destination="home"
            enabled={bootTarget}
            status={agent.status}
            activityState={agent.activityState}
          >
            <AgentOrb
              status={agent.status}
              activityState={agent.activityState}
              size={HOME_AGENT_ORB_SIZE}
            />
          </BootTransitionTarget>
        </Animated.View>
        <Animated.View
          pointerEvents="none"
          style={[
            StyleSheet.absoluteFill,
            {
              opacity: orbReveal.interpolate({
                inputRange: [0, 1],
                outputRange: [0.62, 0],
              }),
            },
          ]}
        >
          <View
            style={[styles.skeletonOrb, { backgroundColor: colors.input }]}
          />
        </Animated.View>
      </Animated.View>
      <View style={styles.agentDetails}>
        <AgentStatusBadge status={agent.status} centered />
        <Text
          family="heading"
          style={[styles.agentName, { color: colors.text }]}
        >
          {agent.name}
        </Text>
      </View>
    </Pressable>
  );
}

function HomeSkeleton() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { colors } = usePreferences();
  const [opacity] = useState(() => new Animated.Value(0.48));
  const [reduceMotion, setReduceMotion] = useState(false);

  useEffect(() => {
    let active = true;
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduceMotion,
    );
    void AccessibilityInfo.isReduceMotionEnabled().then((reduced) => {
      if (active) setReduceMotion(reduced);
    });
    return () => {
      active = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    opacity.setValue(reduceMotion ? 0.62 : 0.48);
    if (reduceMotion) return;

    const pulse = Animated.loop(
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.82,
          duration: 850,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 0.48,
          duration: 850,
          useNativeDriver: true,
        }),
      ]),
    );
    pulse.start();
    return () => pulse.stop();
  }, [opacity, reduceMotion]);

  const placeholder = { backgroundColor: colors.input };

  return (
    <Screen scroll={false} contentStyle={styles.screen}>
      <Stack.Screen
        options={{
          headerLargeTitle: false,
          headerTransparent: true,
          headerStyle: { backgroundColor: "transparent" },
          headerShadowVisible: false,
          headerBackVisible: false,
          headerTitle: () => <HomeWordmark />,
          unstable_headerLeftItems: () => [
            {
              type: "button",
              label: "Settings",
              accessibilityLabel: "Settings",
              icon: { type: "sfSymbol", name: "gearshape" },
              tintColor: colors.text,
              identifier: "home-settings",
              onPress: () => router.push("/settings"),
            },
          ],
          unstable_headerRightItems: () => [],
          headerLeft: () => (
            <HomeHeaderButton
              accessibilityLabel="Settings"
              icon="settings-outline"
              iconSize={21}
              onPress={() => router.push("/settings")}
            />
          ),
          headerRight: () => null,
        }}
      />
      <Animated.View
        accessible
        accessibilityLabel="Opening Vesta"
        accessibilityRole="progressbar"
        accessibilityState={{ busy: true }}
        style={[styles.agentPage, { opacity }]}
      >
        <View style={[styles.skeletonOrb, placeholder]} />
        <View style={styles.agentDetails}>
          <View style={[styles.skeletonStatus, placeholder]} />
          <View style={[styles.skeletonName, placeholder]} />
        </View>
      </Animated.View>
      <Animated.View
        pointerEvents="none"
        style={[
          styles.indicators,
          { bottom: Math.max(insets.bottom, 16), opacity },
        ]}
      >
        <View style={[styles.skeletonActiveIndicator, placeholder]} />
        <View style={[styles.skeletonIndicator, placeholder]} />
        <View style={[styles.skeletonIndicator, placeholder]} />
      </Animated.View>
    </Screen>
  );
}

function HomeWordmark() {
  const { colors } = usePreferences();
  return (
    <View style={styles.wordmarkContainer}>
      <Text family="heading" style={[styles.wordmark, { color: colors.text }]}>
        vesta
      </Text>
    </View>
  );
}

function HomeHeaderButton({
  accessibilityLabel,
  icon,
  iconSize,
  onPress,
}: {
  accessibilityLabel: string;
  icon: ComponentProps<typeof Ionicons>["name"];
  iconSize: number;
  onPress: () => void;
}) {
  const { colors } = usePreferences();
  const content = (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel}
      hitSlop={8}
      onPress={onPress}
      style={({ pressed }) => [
        styles.headerButtonContent,
        { opacity: pressed ? 0.68 : 1 },
      ]}
    >
      <Ionicons name={icon} size={iconSize} color={colors.text} />
    </Pressable>
  );

  return (
    <View style={[styles.headerButton, { backgroundColor: colors.input }]}>
      {content}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { padding: 0 },
  carousel: { backgroundColor: "transparent" },
  empty: { flex: 1, justifyContent: "center", padding: 24 },
  agentPage: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 32,
    paddingHorizontal: 28,
  },
  agentDetails: { alignItems: "center", gap: 6 },
  orbHandoff: {
    width: HOME_AGENT_ORB_SIZE,
    height: HOME_AGENT_ORB_SIZE,
  },
  agentName: { fontSize: 38, fontWeight: "500", letterSpacing: -1 },
  indicators: {
    position: "absolute",
    left: 0,
    right: 0,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
    height: 24,
  },
  indicatorSlot: {
    width: PAGE_DOT_ACTIVE_WIDTH,
    height: PAGE_DOT_SIZE,
    alignItems: "center",
    justifyContent: "center",
  },
  indicatorDot: {
    position: "absolute",
    width: PAGE_DOT_SIZE,
    height: PAGE_DOT_SIZE,
    borderRadius: PAGE_DOT_SIZE / 2,
  },
  indicatorActive: {
    position: "absolute",
    width: PAGE_DOT_ACTIVE_WIDTH,
    height: PAGE_DOT_SIZE,
    borderRadius: PAGE_DOT_SIZE / 2,
  },
  wordmarkContainer: {
    height: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  wordmark: {
    fontSize: 34,
    lineHeight: 36,
    fontWeight: "500",
    letterSpacing: -0.85,
    transform: [{ translateY: 3 }],
  },
  headerButton: {
    width: 40,
    height: 40,
    borderRadius: 20,
    overflow: "hidden",
  },
  headerButtonContent: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
  },
  skeletonOrb: {
    width: HOME_AGENT_ORB_SIZE,
    height: HOME_AGENT_ORB_SIZE,
    borderRadius: HOME_AGENT_ORB_SIZE / 2,
  },
  skeletonStatus: { width: 76, height: 24, borderRadius: 12 },
  skeletonName: { width: 148, height: 38, borderRadius: 12 },
  skeletonActiveIndicator: { width: 22, height: 7, borderRadius: 999 },
  skeletonIndicator: { width: 7, height: 7, borderRadius: 999 },
});
