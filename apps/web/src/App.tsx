import { RouterProvider } from "react-router-dom";
import { AnimatePresence, motion, MotionConfig } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoadingScreen } from "@/components/LoadingScreen";
import { AuthProvider, useAuth } from "@/providers/AuthProvider";
import { GatewayProvider, useGateway } from "@/providers/GatewayProvider";
import { NotificationProvider } from "@/providers/NotificationProvider";
import { InsetFrame } from "@/components/InsetFrame";
import { isTauri } from "@/lib/env";
import { cn } from "@/lib/utils";
import { router } from "@/router";
import { useIsMobile } from "./hooks/use-mobile";
import { useTauri } from "@/providers/TauriProvider";

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
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default function App() {
  const isMobile = useIsMobile();
  const { isLinux } = useTauri();
  const isFullscreen = isMobile || isTauri;

  const content = (
    <div className="relative flex min-h-0 flex-1 flex-col">
      <MotionConfig reducedMotion="user">
        <ErrorBoundary>
          <TooltipProvider delayDuration={300}>
            <AuthProvider>
              <GatewayProvider>
                <NotificationProvider>
                  <AppContent />
                </NotificationProvider>
              </GatewayProvider>
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

  // Mobile / Tauri: the OS window is the frame, so just the muted surface
  // (plus Linux Tauri window-corner rounding) and safe-area insets.
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col bg-muted",
        isLinux && isTauri && "overflow-hidden rounded-xl",
      )}
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pl-[env(safe-area-inset-left)]">
        {content}
      </div>
    </div>
  );
}
