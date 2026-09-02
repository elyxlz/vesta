import type { ReactNode } from "react";
import {
  createAgentRequests,
  createReplica,
  type AgentNode,
  type Controller,
  type GatewayOperation,
  type Tree,
  createSession,
} from "@vesta/core";
import { AppBehindScreen } from "../../src/controller/AppBehindScreen";
import { GatewayUpdateGate } from "../../src/controller/gateway-update-gate";
import { GatewayOperationContext } from "../../src/controller/gateway-operation-context";
import { ControllerContext } from "../../src/controller/context";
import { visualSwitch } from "./launch-query";
import { fixtureAgents, fixtureDevices } from "./roster-provider";
import { notifications } from "./session-provider";

const needsGatewayUpdate = visualSwitch("visualGatewayUpdate") === "required";
const appBehind = visualSwitch("visualSyncState") === "app_behind";
// visualSync=open mounts a controller whose sync socket reads as open, so the
// live edges render: an enabled composer, the typing indicator (with the
// harness chat socket), and pending notifications (visualLive=pending).
const syncOpen = visualSwitch("visualSync") === "open";
const pendingNotifications =
  visualSwitch("visualLive") === "pending" ? notifications.slice(0, 2) : [];

function fixtureTree(): Tree {
  const agents: Record<string, AgentNode> = {};
  for (const agent of fixtureAgents) {
    const { name, ...info } = agent;
    agents[name] = {
      info,
      notifications: { pending: name === "aria" ? pendingNotifications : [] },
    };
  }
  return {
    gateway: {
      version: "0.2.0",
      channel: "stable",
      autoUpdate: true,
      port: 8080,
      lan: { exposed: true, url: "http://vesta.local:8080" },
      tunnelUrl: "https://home.vesta.run",
      updateAvailable: false,
      latestVersion: null,
      managed: false,
      operation: null,
    },
    agents,
    devices: fixtureDevices,
  };
}

function createOpenController(): Controller {
  const replica = createReplica();
  replica.applySnapshot(fixtureTree());
  const noop = () => undefined;
  const unsubscribe = () => noop;
  return {
    replica,
    requests: createAgentRequests(),
    http: {
      request: async () => new Response(null, { status: 204 }),
      // The chat tail seeds from the hold; an empty page keeps it as is.
      json: async <T,>() => ({ events: [], cursor: null }) as T,
    },
    session: createSession({
      fetch: () =>
        Promise.reject(new Error("the visual harness never fetches")),
      read: () => null,
      write: noop,
    }),
    subscribeDeltas: unsubscribe,
    getSyncState: () => "open",
    subscribeSyncState: unsubscribe,
    reportPresence: noop,
    reportViewing: noop,
    reportDeviceContext: noop,
    getFocused: () => true,
    subscribeFocused: unsubscribe,
    getViewing: () => null,
    subscribeViewing: unsubscribe,
    getAnyFocused: () => false,
    subscribeAnyFocused: unsubscribe,
    close: noop,
  };
}

const controller = syncOpen ? createOpenController() : null;

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
    "snapshotting-all",
    {
      kind: "update",
      phase: "snapshotting",
      agent: null,
      done: null,
      total: null,
      targetVersion: "0.2.1",
      warnings: [],
      error: null,
    },
  ],
  [
    "applying",
    {
      kind: "update",
      phase: "applying",
      agent: null,
      done: null,
      total: null,
      targetVersion: "0.2.1",
      warnings: [],
      error: null,
    },
  ],
  [
    "update-restarting",
    {
      kind: "update",
      phase: "restarting",
      agent: null,
      done: null,
      total: null,
      targetVersion: "0.2.1",
      warnings: [],
      error: null,
    },
  ],
  [
    "failed-generic",
    {
      kind: "update",
      phase: "failed",
      agent: null,
      done: null,
      total: null,
      targetVersion: "0.2.1",
      warnings: [
        "forge was not backed up: its export exceeded the pre-update budget.",
      ],
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
const requestedOperation = visualSwitch("visualGatewayOperation");
const operation =
  requestedOperation === null
    ? null
    : (operations.get(requestedOperation) ?? null);
// The moment after an update the client watched: the operation is gone and home reports the version
// it landed on. A live app holds this for a few seconds, so the launch pins it instead.
const updatedTo = visualSwitch("visualGatewayUpdated");

export function ControllerProvider({ children }: { children: ReactNode }) {
  return (
    <ControllerContext.Provider value={controller}>
      <GatewayOperationContext.Provider
        value={{ operation, updatedTo, restarted: false }}
      >
        {appBehind ? (
          <AppBehindScreen />
        ) : (
          <GatewayUpdateGate blocked={needsGatewayUpdate}>
            {children}
          </GatewayUpdateGate>
        )}
      </GatewayOperationContext.Provider>
    </ControllerContext.Provider>
  );
}
