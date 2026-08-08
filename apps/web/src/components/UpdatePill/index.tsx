import { useState } from "react";
import { gatewayOperationLabel } from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

// Renders nothing unless there is something to say about updating, so call sites can drop it
// wherever the pill should surface without re-checking the flags. Three states, all read from the
// gateway itself so every device shows the same one: an update is available, one is running (the
// live phase in the tooltip), or one failed and can be retried.
export function UpdatePill({ className }: { className?: string }) {
  const {
    updateAvailable,
    latestVersion,
    updateOperation,
    triggerGatewayUpdate,
  } = useGateway();
  const [requesting, setRequesting] = useState(false);

  if (updateOperation === null && !updateAvailable) return null;

  const running =
    updateOperation !== null && updateOperation.phase !== "failed";
  const failed = updateOperation?.phase === "failed";

  // The flag covers only the request itself; once vestad answers, the operation on /sync owns the
  // pill's state. A granted request that kept the flag would leave the next failure's retry stuck.
  const handleUpdate = async () => {
    setRequesting(true);
    await triggerGatewayUpdate();
    setRequesting(false);
  };

  const title = () => {
    if (updateOperation !== null) return gatewayOperationLabel(updateOperation);
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
      {running ? "updating" : failed ? "retry" : "update"}
    </Button>
  );
}
