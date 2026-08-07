import { useEffect, useRef } from "react";
import { StyleSheet, View } from "react-native";
import {
  useIsFocused,
  useLocalSearchParams,
  useRouter,
  useSegments,
} from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AgentOrb } from "@/components/AgentOrb";
import {
  BootTransitionTarget,
  useBootTransitionPhase,
} from "@/components/BootTransition";
import { VestaBrand } from "@/components/VestaBrand";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { usePrivacyBlocked } from "@/privacy/use-privacy-blocked";
import { useSession } from "@/session/SessionProvider";

export default function ConnectScreen() {
  return <ConnectContent />;
}

function ConnectContent() {
  const insets = useSafeAreaInsets();
  const parameters = useLocalSearchParams<{ link?: string | string[] }>();
  const parameterLink = Array.isArray(parameters.link)
    ? parameters.link[0]
    : parameters.link;
  const initialLink =
    typeof parameterLink === "string" && parameterLink.startsWith("https://")
      ? parameterLink
      : "";
  const router = useRouter();
  const isFocused = useIsFocused();
  const segments = useSegments();
  const activeRoute = segments[0];
  const bootTransition = useBootTransitionPhase();
  const { recentGateways } = useSession();
  const { colors } = usePreferences();
  const privacyBlocked = usePrivacyBlocked();
  const initialDrawerOpened = useRef(false);
  const nextScreenOpened = useRef(false);
  const estimatedActionSheetHeight = recentGateways?.length ? 186 : 156;
  const canPresentSheet =
    !privacyBlocked &&
    (!bootTransition.active || bootTransition.pageRevealed);

  useEffect(() => {
    if (!isFocused) {
      nextScreenOpened.current = false;
      return;
    }
    if (!canPresentSheet) return;
    if (nextScreenOpened.current) return;
    nextScreenOpened.current = true;

    if (initialLink && !initialDrawerOpened.current) {
      initialDrawerOpened.current = true;
      router.push({ pathname: "/connect-link", params: { link: initialLink } });
      return;
    }

    router.push("/connect-actions");
  }, [canPresentSheet, initialLink, isFocused, router]);

  return (
    <View
      style={[
        styles.screen,
        {
          backgroundColor: colors.background,
          paddingTop: Math.max(insets.top, 24),
        },
      ]}
    >
      <View
        style={[
          styles.hero,
          { paddingBottom: estimatedActionSheetHeight },
        ]}
      >
        <VestaBrand
          orb={
            <BootTransitionTarget destination="connect" status="alive">
              <AgentOrb
                status="alive"
                size={88}
                pulseScale={1.12}
                pulseDuration={1400}
                pulseHaptics={
                  activeRoute === "connect" || activeRoute === "connect-actions"
                }
              />
            </BootTransitionTarget>
          }
        />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  hero: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
});
