import { useState } from "react";
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ProgressBar } from "@/components/ProgressBar";
import { ProviderPicker } from "@/components/ProviderPicker";
import { setProvider } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useModals } from "@/providers/ModalsProvider";

export function AgentIslandModals() {
  const { name } = useSelectedAgent();
  const {
    showAuth,
    clearAuthState,
    deleteDialogOpen,
    setDeleteDialogOpen,
    handleDelete,
  } = useModals();

  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  return (
    <>
      <Dialog
        drawerOnMobile
        open={showAuth}
        onOpenChange={(open) => {
          if (!open) {
            clearAuthState();
            setSubmitError(null);
            setSubmitting(false);
          }
        }}
      >
        <DialogContent className="sm:max-w-lg" showCloseButton>
          <DialogHeader>
            <DialogTitle>provider for {name}</DialogTitle>
            <DialogDescription className="sr-only">
              switch providers or refresh credentials for this agent
            </DialogDescription>
          </DialogHeader>
          {submitting ? (
            <div className="flex flex-col items-center gap-3 py-4">
              <ProgressBar message="applying new provider config..." />
            </div>
          ) : (
            <div className="flex min-w-0 flex-col items-center gap-3 py-2">
              <ProviderPicker
                className="w-full px-0"
                onDone={async (result) => {
                  setSubmitting(true);
                  setSubmitError(null);
                  try {
                    await setProvider(name, result);
                    clearAuthState();
                  } catch (e: unknown) {
                    setSubmitError(
                      (e as { message?: string })?.message ||
                        "failed to update provider",
                    );
                  } finally {
                    setSubmitting(false);
                  }
                }}
              />
              {submitError && (
                <p className="text-xs text-destructive text-center">
                  {submitError}
                </p>
              )}
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
