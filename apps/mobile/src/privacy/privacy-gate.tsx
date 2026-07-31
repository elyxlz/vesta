import { useEffect, useRef, type ReactNode } from "react";
import { useRouter, useSegments, type Href } from "expo-router";
import { PrivacyGateView } from "./privacy-gate-view";
import { blocksProtectedContent } from "./model";
import { usePrivacy } from "./privacy-provider";

const PRIVACY_ROUTE = "/privacy" as Href;
const ROOT_ROUTE = "/" as Href;
const NATIVE_SHEET_ROUTES = new Set([
  "connect-actions",
  "connect-link",
  "debug",
  "new-agent",
  "recent-gateways",
  "scan",
  "settings",
  "whats-new",
]);

export function PrivacyGate({ children }: { children: ReactNode }) {
  const privacy = usePrivacy();
  const router = useRouter();
  const segments = useSegments();
  const presentationPending = useRef(false);
  const blocked = blocksProtectedContent(
    privacy.hydrated,
    privacy.locked,
    privacy.initializationError !== null,
  );
  const activeRoute = segments[0] as string | undefined;
  const privacyRouteActive = activeRoute === "privacy";

  useEffect(() => {
    if (blocked) {
      if (privacyRouteActive) {
        presentationPending.current = false;
        return;
      }
      if (presentationPending.current) return;

      presentationPending.current = true;
      if (activeRoute && NATIVE_SHEET_ROUTES.has(activeRoute)) {
        router.replace(PRIVACY_ROUTE);
      } else {
        router.push(PRIVACY_ROUTE);
      }
      return;
    }

    presentationPending.current = false;
    if (!privacyRouteActive) return;
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace(ROOT_ROUTE);
    }
  }, [activeRoute, blocked, privacyRouteActive, router]);

  return (
    <PrivacyGateView blocked={blocked}>
      {children}
    </PrivacyGateView>
  );
}
