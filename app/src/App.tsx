import { useCallback } from "react";
import { RouterProvider } from "react-router-dom";
import { AnimatePresence, motion } from "motion/react";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LoadingScreen } from "@/components/LoadingScreen";
import "@/stores/use-theme";
import { AuthProvider, useAuth } from "@/providers/AuthProvider";
import { AgentsProvider } from "@/providers/AgentsProvider";
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
          className="h-full"
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

export function App() {
  return (
    <TooltipProvider delayDuration={300}>
      <AuthProvider>
        <AgentsProvider>
          <AppContent />
        </AgentsProvider>
      </AuthProvider>
    </TooltipProvider>
  );
}
