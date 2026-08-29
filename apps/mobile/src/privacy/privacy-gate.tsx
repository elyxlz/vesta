import { useEffect, useRef, type ReactNode } from "react";
import { useRouter, useSegments, type Href } from "expo-router";
import { BlockingSheetGateView } from "@/components/blocking-sheet-gate-view";
import { usePreferences } from "@/preferences/PreferencesProvider";
import { useSession } from "@/session/SessionProvider";
import {
  privacyGateNavigationAction,
  shouldAutomaticallyUnlock,
} from "./privacy-gate-model";
import { usePrivacy } from "./privacy-provider";
import { usePrivacyBlocked } from "./use-privacy-blocked";

const PRIVACY_ROUTE = "/privacy" as Href;
const ROOT_ROUTE = "/" as Href;
const CONNECT_ROUTE = "/connect" as Href;
const ESTIMATED_PRIVACY_SHEET_HEIGHT = 181;
const NATIVE_SHEET_ROUTES = new Set([
  "connect-actions",
  "connect-link",
  "debug",
  "gateway-update",
  "new-agent",
  "recent-gateways",
  "scan",
  "settings",
  "switch-gateway",
  "whats-new",
]);

export function PrivacyGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const segments = useSegments();
  const { status } = useSession();
  const { hydrated: preferencesHydrated } = usePreferences();
  const privacy = usePrivacy();
  const presentationPending = useRef(false);
  const automaticUnlockAttempted = useRef(false);
  const blocked = usePrivacyBlocked();
  const activeRoute = segments[0] as string | undefined;
  const privacyRouteActive = activeRoute === "privacy";
  const presentationReady =
    preferencesHydrated && privacy.hydrated && status !== "booting";
  const action = privacyGateNavigationAction({
    blocked,
    presentationReady,
    privacyRouteActive,
    replaceActiveRoute: Boolean(
      activeRoute && NATIVE_SHEET_ROUTES.has(activeRoute),
    ),
    sessionStatus: status,
    canGoBack: router.canGoBack(),
  });

  useEffect(() => {
    if (action === "none") {
      presentationPending.current = false;
      return;
    }

    if (action === "back") {
      presentationPending.current = false;
      router.back();
      return;
    }
    if (action === "dismiss-to-connect") {
      presentationPending.current = false;
      router.dismissTo(CONNECT_ROUTE);
      return;
    }
    if (action === "replace-root") {
      presentationPending.current = false;
      router.replace(ROOT_ROUTE);
      return;
    }

    if (presentationPending.current) return;
    presentationPending.current = true;
    if (action === "replace-privacy") {
      router.replace(PRIVACY_ROUTE);
    } else {
      router.push(PRIVACY_ROUTE);
    }
  }, [action, router]);

  useEffect(() => {
    if (!privacy.locked) {
      automaticUnlockAttempted.current = false;
      return;
    }
    if (
      !shouldAutomaticallyUnlock({
        presentationReady,
        privacyRouteActive,
        hydrated: privacy.hydrated,
        locked: privacy.locked,
        authenticating: privacy.authenticating,
        initializationFailed: privacy.initializationError !== null,
        attempted: automaticUnlockAttempted.current,
      })
    ) {
      return;
    }

    automaticUnlockAttempted.current = true;
    void privacy.unlock();
  }, [presentationReady, privacy, privacyRouteActive]);

  // Before hydration the lock state is unknown and the boot splash already
  // covers the app, so painting the hero then only flashes it over the splash.
  return (
    <BlockingSheetGateView
      blocked={blocked && privacy.hydrated}
      presented={privacyRouteActive}
      estimatedSheetHeight={ESTIMATED_PRIVACY_SHEET_HEIGHT}
    >
      {children}
    </BlockingSheetGateView>
  );
}
