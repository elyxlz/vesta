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
} from "@/components/Dialog";
import { BackupsDialog } from "@/components/BackupsDialog";
import { ProgressBar } from "@/components/ProgressBar";
import { ProviderPicker } from "@/components/ProviderPicker";
import { setProvider } from "@/api/agents";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { useDialogs } from "@/stores/use-dialogs";
import { useNavigate } from "react-router-dom";

export function AgentIslandModals() {
  const { name, remove } = useSelectedAgent();
  const navigate = useNavigate();
  const dialogs = useDialogs((s) => s.open);
  const setDialogOpen = useDialogs((s) => s.setOpen);
  const showAuth = dialogs.providerAuth;
  const clearAuthState = () => {
    setDialogOpen("providerAuth", false);
  };
  const handleDelete = async () => {
    await navigate("/");
    await remove();
  };

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
                agentName={name}
                className="w-full px-0"
                onDone={(result) => {
                  const submit = async () => {
                    setSubmitting(true);
                    setSubmitError(null);
                    try {
                      await setProvider(name, result);
                      clearAuthState();
                    } catch (e: unknown) {
                      setSubmitError(
                        e instanceof Error
                          ? e.message
                          : "failed to update provider",
                      );
                    } finally {
                      setSubmitting(false);
                    }
                  };
                  void submit();
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

      <AlertDialog
        open={dialogs.deleteAgent}
        onOpenChange={(open) => {
          setDialogOpen("deleteAgent", open);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>delete {name}?</AlertDialogTitle>
            <AlertDialogDescription>
              this permanently deletes {name} and everything they've learned. it
              can't be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>cancel</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                void handleDelete();
              }}
            >
              delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <BackupsDialog
        open={dialogs.backups}
        onOpenChange={(open) => {
          setDialogOpen("backups", open);
        }}
      />
    </>
  );
}
