import { useState } from "react";
import { gatewayOperationLabel } from "@vesta/core";
import { useGateway } from "@/providers/GatewayProvider/context";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  Empty,
  EmptyHeader,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty";

// The one screen a gateway update lives on, from the first pre-update backup to the moment the app
// reconnects on the new version. It takes over home while the update runs (agent pages are
// unavailable, settings stay reachable) and morphs through the phases in place, so a slow backup and
// a restart read as the same operation rather than the app changing mode under the user.
export function UpdateProgressScreen() {
  const { updateOperation, updatedTo, triggerGatewayUpdate, dismissUpdate } =
    useGateway();
  const [retrying, setRetrying] = useState(false);

  if (updateOperation === null) {
    if (updatedTo === null) return null;
    return (
      <Empty>
        <EmptyHeader className="max-w-lg">
          <EmptyTitle>updated to v{updatedTo}</EmptyTitle>
          <EmptyDescription>
            your gateway is on the new version.
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  const failed = updateOperation.phase === "failed";

  const handleRetry = async () => {
    setRetrying(true);
    if (!(await triggerGatewayUpdate())) setRetrying(false);
  };

  return (
    <Empty>
      <EmptyHeader className="max-w-lg">
        <EmptyTitle>
          {failed
            ? "update failed"
            : `updating to v${updateOperation.targetVersion}`}
        </EmptyTitle>
        <EmptyDescription>
          {failed
            ? (updateOperation.error ??
              "the update stopped before it finished. your agents are untouched.")
            : "Vesta backs up every agent before installing, so this can take a few minutes. keep the app open."}
        </EmptyDescription>
      </EmptyHeader>
      <EmptyContent>
        {failed ? (
          <div className="flex items-center gap-2">
            <Button
              onClick={() => {
                void handleRetry();
              }}
              disabled={retrying}
            >
              {retrying && <Spinner className="size-4" />}
              retry
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                void dismissUpdate();
              }}
            >
              dismiss
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner className="size-4" />
            {gatewayOperationLabel(updateOperation)}
          </div>
        )}
        {updateOperation.warnings.length > 0 && (
          <div className="max-w-lg text-xs text-muted-foreground">
            {updateOperation.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        )}
      </EmptyContent>
    </Empty>
  );
}
