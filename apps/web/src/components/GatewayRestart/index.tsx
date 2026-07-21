import { useState } from "react";
import { RotateCw } from "lucide-react";
import { useGateway } from "@/providers/GatewayProvider";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";

// Restart the gateway from the connection card. A restart drops every agent
// connection briefly, so it confirms first; on accept the app re-attaches via
// the same reconnect the update flow uses (triggerGatewayRestart calls reconnect).
export function GatewayRestart() {
  const { triggerGatewayRestart } = useGateway();
  const [restarting, setRestarting] = useState(false);

  const handleRestart = async () => {
    setRestarting(true);
    const ok = await triggerGatewayRestart();
    if (!ok) setRestarting(false);
  };

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button
          variant="outline"
          className="w-full shrink-0 whitespace-nowrap sm:w-auto"
          disabled={restarting}
        >
          {restarting ? (
            <Spinner className="size-4" data-icon="inline-start" />
          ) : (
            <RotateCw data-icon="inline-start" />
          )}
          restart
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>restart the gateway?</AlertDialogTitle>
          <AlertDialogDescription>
            this briefly drops every agent connection while the gateway restarts.
            the app reconnects on its own once it's back.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={() => {
              void handleRestart();
            }}
          >
            restart
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
