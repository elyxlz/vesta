import type { ReactNode } from "react";
import * as Linking from "expo-linking";
import type { GatewayOperation } from "@vesta/core";
import { GatewayUpdateGate } from "../../src/controller/gateway-update-gate";
import { GatewayOperationContext } from "../../src/controller/gateway-operation-context";
import { ControllerContext } from "../../src/controller/context";

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const needsGatewayUpdate = query?.visualGatewayUpdate === "required";

// The gateway operation /sync would carry, one fixed value per launch. The tree holds at most one
// operation at a time and no public action moves it from one phase to the next, so each state is
// its own launch. Names and versions match the roster fixture's gateway.
const operations = new Map<string, GatewayOperation>([
  [
    "snapshotting",
    {
      kind: "update",
      phase: "snapshotting",
      agent: "nova",
      done: 1,
      total: 3,
      targetVersion: "0.2.1",
      warnings: [],
      error: null,
    },
  ],
  [
    "failed",
    {
      kind: "update",
      phase: "failed",
      agent: "nova",
      done: 1,
      total: 3,
      targetVersion: "0.2.1",
      warnings: [],
      error:
        "Backing up nova stopped: the gateway ran out of disk space. Your agents are untouched.",
    },
  ],
  [
    "restarting",
    {
      kind: "restart",
      phase: "restarting",
      agent: null,
      done: null,
      total: null,
      targetVersion: null,
      warnings: [],
      error: null,
    },
  ],
]);
const requestedOperation = query?.visualGatewayOperation;
const operation =
  typeof requestedOperation === "string"
    ? (operations.get(requestedOperation) ?? null)
    : null;
// The moment after an update the client watched: the operation is gone and home reports the version
// it landed on. A live app holds this for a few seconds, so the launch pins it instead.
const requestedUpdatedTo = query?.visualGatewayUpdated;
const updatedTo =
  typeof requestedUpdatedTo === "string" ? requestedUpdatedTo : null;

export function ControllerProvider({ children }: { children: ReactNode }) {
  return (
    <ControllerContext.Provider value={null}>
      <GatewayOperationContext.Provider value={{ operation, updatedTo }}>
        <GatewayUpdateGate blocked={needsGatewayUpdate}>
          {children}
        </GatewayUpdateGate>
      </GatewayOperationContext.Provider>
    </ControllerContext.Provider>
  );
}
