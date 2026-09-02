import { RouterProvider } from "react-router-dom";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoadingScreen } from "@/components/LoadingScreen";
import { AuthProvider } from "@/providers/AuthProvider";
import { useAuth } from "@/providers/AuthProvider/context";
import { ControllerProvider } from "@/providers/ControllerProvider";
import { GatewayProvider } from "@/providers/GatewayProvider";
import { useGateway } from "@/providers/GatewayProvider/context";
import { NotificationProvider } from "@/providers/NotificationProvider";
import { PresenceReporter } from "@/providers/PresenceReporter";
import { InsetFrame } from "@/components/InsetFrame";
import { Scrim } from "@/components/Scrim";
import { WhatsNewDialog } from "@/components/WhatsNew";
import { SwitchGatewayDialog } from "@/components/SwitchGatewayDialog";
import { router } from "@/router";
import { useAutoHideScrollbars } from "./use-auto-hide-scrollbars";
import { useIsMobile } from "./hooks/use-mobile";
import { useRuntime } from "@/providers/RuntimeProvider";

function openAgent(agentName: string): void {
  void router.navigate(`/agent/${encodeURIComponent(agentName)}`);
}

function AppContent() {
  const { loading, initialized, setLoading } = useAuth();
  const { versionChecked } = useGateway();

  return (
    <AnimatePresence mode="wait">
      {loading ? (
        <LoadingScreen
          key="loading"
          ready={initialized && versionChecked}
          onFinished={() => setLoading(false)}
        />
      ) : (
        <motion.div
          key="app"
          className="flex min-h-0 flex-1 flex-col"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3 }}
        >
          <RouterProvider router={router} />
          <WhatsNewDialog />
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function App() {
  const isMobile = useIsMobile();
  const { isDesktopApp } = useRuntime();
  const isFullscreen = isMobile || isDesktopApp;
  useAutoHideScrollbars();

  const content = (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <MotionConfig reducedMotion="user">
        <ErrorBoundary>
          <TooltipProvider delayDuration={300}>
            <AuthProvider>
              <ControllerProvider>
                <GatewayProvider>
                  <NotificationProvider onOpenAgent={openAgent}>
                    <PresenceReporter />
                    <Scrim />
                    <SwitchGatewayDialog />
                    <AppContent />
                  </NotificationProvider>
                </GatewayProvider>
              </ControllerProvider>
            </AuthProvider>
          </TooltipProvider>
        </ErrorBoundary>
      </MotionConfig>
    </div>
  );

  // Web desktop: the rounded "framed window" is faked by the InsetFrame overlay.
  if (!isFullscreen) {
    return <InsetFrame>{content}</InsetFrame>;
  }

  // Mobile / desktop app: the OS window is the frame, so just the muted
  // surface and safe-area insets.
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-muted">
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pl-[env(safe-area-inset-left)]">
        {content}
      </div>
    </div>
  );
}
