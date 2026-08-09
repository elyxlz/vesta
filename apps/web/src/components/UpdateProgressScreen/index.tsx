import { useState } from "react";
import { gatewayOperationLabel, type GatewayOperation } from "@vesta/core";
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

// What the screen calls the operation it is watching, and what it tells the user to expect. A
// restart names no release and touches nothing, so it says so.
function operationCopy(operation: GatewayOperation): {
  title: string;
  detail: string;
} {
  if (operation.phase === "failed") {
    return {
      title: "update failed",
      detail:
        operation.error ??
        "the update stopped before it finished. your agents are untouched.",
    };
  }
  if (operation.kind === "restart") {
    return {
      title: "restarting the gateway",
      detail:
        "your agents keep running. the app reconnects on its own once the gateway is back.",
    };
  }
  return {
    title: `updating to v${operation.targetVersion ?? ""}`,
    detail:
      "your gateway backs up every agent before installing, so this can take a few minutes. keep the app open.",
  };
}

// The one screen a gateway operation lives on, from the first pre-update backup to the moment the
// app reconnects on the new version. It takes over home while the operation runs (agent pages are
// unavailable, settings stay reachable) and morphs through the phases in place, so a slow backup and
// a restart read as the same operation rather than the app changing mode under the user. A bare
// gateway restart is an operation too, and lands on this screen at its one phase.
export function UpdateProgressScreen() {
  const { gatewayOperation, updatedTo, triggerGatewayUpdate, dismissUpdate } =
    useGateway();
  const [retrying, setRetrying] = useState(false);

  if (gatewayOperation === null) {
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

  const failed = gatewayOperation.phase === "failed";
  const { title, detail } = operationCopy(gatewayOperation);

  // The flag covers only the request itself; once vestad answers, the operation's phase owns this
  // screen. A granted retry that kept the flag would leave a second failure's retry stuck.
  const handleRetry = async () => {
    setRetrying(true);
    await triggerGatewayUpdate();
    setRetrying(false);
  };

  return (
    <Empty>
      <EmptyHeader className="max-w-lg">
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{detail}</EmptyDescription>
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
            {gatewayOperationLabel(gatewayOperation)}
          </div>
        )}
        {gatewayOperation.warnings.length > 0 && (
          <div className="max-w-lg text-xs text-muted-foreground">
            {gatewayOperation.warnings.map((warning) => (
              <p key={warning}>{warning}</p>
            ))}
          </div>
        )}
      </EmptyContent>
    </Empty>
  );
}
