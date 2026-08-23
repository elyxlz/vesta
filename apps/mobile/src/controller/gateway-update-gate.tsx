import { useEffect, useRef, type ReactNode } from "react";
import { useRouter, useSegments, type Href } from "expo-router";
import { BlockingSheetGateView } from "@/components/blocking-sheet-gate-view";
import { usePrivacyBlocked } from "@/privacy/use-privacy-blocked";
import { useGatewayOperation } from "./gateway-operation-context";
import { gatewayUpdateGateDecision } from "./gateway-update-gate-model";

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
  const privacyRouteActive = activeRoute === "privacy";
  const gatewayUpdateRouteActive = activeRoute === "gateway-update";
  const privacyBlocked = usePrivacyBlocked();
  const { operation, updatedTo, restarted } = useGatewayOperation();
  const operationPresented =
    operation !== null || updatedTo !== null || restarted;
  const { action, backdropBlocked } = gatewayUpdateGateDecision({
    blocked,
    operationPresented,
    privacyBlocked,
    privacyRouteActive,
    gatewayUpdateRouteActive,
    replaceActiveRoute: Boolean(
      activeRoute && NATIVE_SHEET_ROUTES.has(activeRoute),
    ),
  });

  useEffect(() => {
    // Privacy owns navigation until its route is gone. Waiting through the unlocked dismissal
    // prevents a push and back in the same commit from leaving privacy beneath this sheet.
    if (action === "none") {
      presentationPending.current = false;
      return;
    }

    if (action === "dismiss") {
      presentationPending.current = false;
      if (router.canGoBack()) {
        router.back();
      } else {
        router.replace(ROOT_ROUTE);
      }
      return;
    }

    if (presentationPending.current) return;
    presentationPending.current = true;
    if (action === "replace-update") {
      router.replace(GATEWAY_UPDATE_ROUTE);
    } else {
      router.push(GATEWAY_UPDATE_ROUTE);
    }
  }, [action, router]);

  return (
    <BlockingSheetGateView
      blocked={backdropBlocked}
      presented={gatewayUpdateRouteActive}
      estimatedSheetHeight={ESTIMATED_GATEWAY_UPDATE_SHEET_HEIGHT}
    >
      {children}
    </BlockingSheetGateView>
  );
}
