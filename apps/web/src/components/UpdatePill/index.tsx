import { useState } from "react";
import { gatewayOperationLabel } from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

// Renders nothing unless there is something to say about the gateway, so call sites can drop it
// wherever the pill should surface without re-checking the flags. Four states, all read from the
// gateway itself so every device shows the same one: an update is available, one is running (the
// live phase in the tooltip), one failed and can be retried, or the gateway is restarting, which
// disables the pill exactly like a running update.
export function UpdatePill({ className }: { className?: string }) {
  const {
    updateAvailable,
    latestVersion,
    gatewayOperation,
    triggerGatewayUpdate,
  } = useGateway();
  const [requesting, setRequesting] = useState(false);

  if (gatewayOperation === null && !updateAvailable) return null;

  const running =
    gatewayOperation !== null && gatewayOperation.phase !== "failed";
  const failed = gatewayOperation?.phase === "failed";
  const restarting = gatewayOperation?.kind === "restart";

  // The flag covers only the request itself; once vestad answers, the operation on /sync owns the
  // pill's state. A granted request that kept the flag would leave the next failure's retry stuck.
  const handleUpdate = async () => {
    setRequesting(true);
    await triggerGatewayUpdate();
    setRequesting(false);
  };

  const title = () => {
    if (gatewayOperation !== null)
      return gatewayOperationLabel(gatewayOperation);
    return latestVersion ? `Update to v${latestVersion}` : "Update available";
  };

  return (
    <Button
      size="xs"
      onClick={() => {
        void handleUpdate();
      }}
      disabled={running || requesting}
      className={className}
      title={title()}
    >
      {(running || requesting) && <Spinner className="size-3" />}
      {running && restarting
        ? "restarting"
        : running
          ? "updating"
          : failed
            ? "retry"
            : "update"}
    </Button>
  );
}
