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
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

export function AgentIslandModals() {
  const { name, agent } = useSelectedAgent();
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
            <DialogDescription className="sr-only">
              complete sign-in for this agent
            </DialogDescription>
          </DialogHeader>
          {authStart ? (
            <AuthFlow
              agentName={name}
              authUrl={authStart.auth_url}
              sessionId={authStart.session_id}
              onCancel={clearAuthState}
              onComplete={() => {
                clearAuthState();
              }}
            />
          ) : authStarting ? (
            <div className="flex flex-col items-center gap-3 py-2">
              <p className="text-sm text-muted-foreground">
                starting authentication...
              </p>
              <ProgressBar message="waiting..." />
              <Button variant="link" size="sm" onClick={clearAuthState}>
                cancel
              </Button>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3 py-2">
              <p className="text-xs text-destructive text-center">
                {authError || "authentication failed"}
              </p>
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
              this will permanently destroy the agent and all its data. this
              action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={handleDelete}>
              delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
