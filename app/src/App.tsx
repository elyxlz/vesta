import { RouterProvider } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoadingScreen } from "@/components/LoadingScreen";
import { AuthProvider, useAuth } from "@/providers/AuthProvider";
import { GatewayProvider, useGateway } from "@/providers/GatewayProvider";
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

  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col",
        isFullscreen ? "bg-muted" : "p-3.5 max-sm:p-2",
        isLinux && isTauri && "overflow-hidden rounded-xl",
      )}
    >
      <div
        className={cn(
          "flex min-h-0 flex-1 flex-col overflow-hidden pt-[env(safe-area-inset-top)] pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)]",
          !isFullscreen &&
            "bg-muted border border-border rounded-squircle-md [corner-shape:squircle]",
        )}
      >
        <div className="relative flex min-h-0 flex-1 flex-col">
          <ErrorBoundary>
            <TooltipProvider delayDuration={300}>
              <AuthProvider>
                <GatewayProvider>
                  <AppContent />
                </GatewayProvider>
              </AuthProvider>
            </TooltipProvider>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}
