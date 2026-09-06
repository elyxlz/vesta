import { useEffect, useRef } from "react";
import { StyleSheet, View } from "react-native";
import {
  useIsFocused,
  useLocalSearchParams,
  useRouter,
  useSegments,
} from "expo-router";
import { AgentOrb } from "@/components/AgentOrb";
import {
  BootTransitionTarget,
  useBootTransitionPhase,
} from "@/components/BootTransition";
import { BRAND_ORB_SIZE } from "@/components/VestaBrand";
import { BrandBackdrop } from "@/components/brand-backdrop";
import { usePrivacyBlocked } from "@/privacy/use-privacy-blocked";

export default function ConnectScreen() {
  return <ConnectContent />;
}

function ConnectContent() {
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
  const activeRoute = segments.find((segment) => !segment.startsWith("("));
  const bootTransition = useBootTransitionPhase();
  const privacyBlocked = usePrivacyBlocked();
  const initialDrawerOpened = useRef(false);
  const nextScreenOpened = useRef(false);
  const canPresentSheet =
    !privacyBlocked && (!bootTransition.active || bootTransition.pageRevealed);

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
    <View style={styles.screen}>
      <BrandBackdrop
        orb={
          <BootTransitionTarget destination="connect" status="alive">
            <AgentOrb
              status="alive"
              size={BRAND_ORB_SIZE}
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
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
});
