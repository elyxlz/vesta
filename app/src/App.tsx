import { useCallback } from "react";
import { RouterProvider } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { LoadingScreen } from "@/components/LoadingScreen";
import { AuthProvider, useAuth } from "@/providers/AuthProvider";
import { AgentsProvider } from "@/providers/AgentsProvider";
import { isTauri } from "@/lib/env";
import { cn } from "@/lib/utils";
import { router } from "@/router";

function AppContent() {
  const { loading, initialized, setLoading } = useAuth();
  const onFinished = useCallback(() => setLoading(false), [setLoading]);

  return (
    <AnimatePresence mode="wait">
      {loading ? (
        <LoadingScreen
          key="loading"
          ready={initialized}
          onFinished={onFinished}
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
  return (
    <div
      className={cn(
        "flex min-h-0 flex-1 flex-col",
        !isTauri && "p-3.5 max-sm:p-2",
      )}
    >
      <div
        className={cn(
          "relative flex min-h-0 flex-1 flex-col border border-border bg-muted",
          !isTauri && "rounded-3xl",
        )}
      >
        <ErrorBoundary>
          <TooltipProvider delayDuration={300}>
            <AuthProvider>
              <AgentsProvider>
                <AppContent />
              </AgentsProvider>
            </AuthProvider>
          </TooltipProvider>
        </ErrorBoundary>
      </div>
    </div>
  );
}
