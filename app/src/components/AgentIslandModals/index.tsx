import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { Console } from "@/components/Console";
import { isTauri } from "@/lib/env";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProgressBar } from "@/components/ProgressBar";
import { AuthFlow } from "@/components/AuthFlow";
import { cn } from "@/lib/utils";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

export function AgentIslandModals() {
  const { name, agent, restart } = useSelectedAgent();
  const {
    showAuth,
    authStarting,
    authStart,
    authError,
    handleOpenAuth,
    clearAuthState,
    deleteDialogOpen,
    setDeleteDialogOpen,
    handleDelete,
    showConsole,
    setShowConsole,
  } = useModals();

  return (
    <>
      <Dialog
        drawerOnMobile
        open={showAuth && agent?.status === "running"}
        onOpenChange={(open) => {
          if (!open) clearAuthState();
        }}
      >
        <DialogContent className="sm:max-w-lg" showCloseButton>
          <DialogHeader>
            <DialogTitle>authenticate {name}</DialogTitle>
            <DialogDescription className="sr-only">complete sign-in for this agent</DialogDescription>
          </DialogHeader>
          {authStart ? (
            <AuthFlow
              agentName={name}
              authUrl={authStart.auth_url}
              sessionId={authStart.session_id}
              onCancel={clearAuthState}
              onComplete={async () => {
                clearAuthState();
                await restart();
              }}
            />
          ) : authStarting ? (
            <div className="flex flex-col items-center gap-3 py-2">
              <p className="text-sm text-muted-foreground">starting authentication...</p>
              <ProgressBar message="waiting..." />
              <Button variant="link" size="sm" onClick={clearAuthState}>
                cancel
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-2">
              <p className="text-xs text-destructive text-center">{authError || "authentication failed"}</p>
              <Button size="sm" onClick={() => void handleOpenAuth()}>
                retry
              </Button>
              <Button variant="link" size="sm" onClick={clearAuthState}>
                cancel
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>delete {name}?</AlertDialogTitle>
            <AlertDialogDescription>
              this will permanently destroy the agent and all its data. this action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={handleDelete}
            >
              delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {createPortal(
        <AnimatePresence>
          {showConsole && agent?.alive && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              className={cn("fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-5", isTauri && "pt-7")}
              onClick={(e) => {
                if (e.target === e.currentTarget) setShowConsole(false);
              }}
            >
              <motion.div
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="flex min-h-0 min-w-0 w-full h-full max-w-4xl max-h-[800px] flex-col dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8] rounded-none sm:rounded-xl overflow-hidden shadow-2xl"
              >
                <Console
                  name={name}
                  onClose={() => setShowConsole(false)}
                />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>,
        document.body,
      )}
    </>
  );
}
