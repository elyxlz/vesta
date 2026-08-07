import { useEffect, useRef, type ReactNode } from "react";
import { useRouter, useSegments, type Href } from "expo-router";
import { BlockingSheetGateView } from "@/components/blocking-sheet-gate-view";
import { usePrivacyBlocked } from "@/privacy/use-privacy-blocked";

const GATEWAY_UPDATE_ROUTE = "/gateway-update" as Href;
const ROOT_ROUTE = "/" as Href;
const ESTIMATED_GATEWAY_UPDATE_SHEET_HEIGHT = 286;
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

interface GatewayUpdateGateProps {
  blocked: boolean;
  children: ReactNode;
}

export function GatewayUpdateGate({
  blocked,
  children,
}: GatewayUpdateGateProps) {
  const router = useRouter();
  const segments = useSegments();
  const presentationPending = useRef(false);
  const activeRoute = segments[0] as string | undefined;
  const gatewayUpdateRouteActive = activeRoute === "gateway-update";
  const privacyBlocked = usePrivacyBlocked();
  const gatewayUpdateBlocked = blocked && !privacyBlocked;

  useEffect(() => {
    // Privacy owns navigation while it is blocked. It replaces any active sheet and the gateway
    // update waits until privacy clears, so simultaneous state changes cannot stack two sheets.
    if (privacyBlocked) {
      presentationPending.current = false;
      return;
    }

    if (gatewayUpdateBlocked) {
      if (gatewayUpdateRouteActive) {
        presentationPending.current = false;
        return;
      }
      if (presentationPending.current) return;

      presentationPending.current = true;
      if (activeRoute && NATIVE_SHEET_ROUTES.has(activeRoute)) {
        router.replace(GATEWAY_UPDATE_ROUTE);
      } else {
        router.push(GATEWAY_UPDATE_ROUTE);
      }
      return;
    }

    presentationPending.current = false;
    if (!gatewayUpdateRouteActive) return;
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace(ROOT_ROUTE);
    }
  }, [
    activeRoute,
    gatewayUpdateBlocked,
    gatewayUpdateRouteActive,
    privacyBlocked,
    router,
  ]);

  return (
    <BlockingSheetGateView
      blocked={gatewayUpdateBlocked}
      estimatedSheetHeight={ESTIMATED_GATEWAY_UPDATE_SHEET_HEIGHT}
    >
      {children}
    </BlockingSheetGateView>
  );
}
