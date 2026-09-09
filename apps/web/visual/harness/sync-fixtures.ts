import type { Page } from "@playwright/test";
import { directRoomId } from "@vesta/core";
import type {
  AgentInfo,
  AgentNode,
  AgentStatus,
  BuildPhase,
  Delta,
  DeviceInfo,
  GatewayInfo,
  Room,
  Tree,
} from "@vesta/core";

// Version pair mirrors the locked sync-protocol.json fixture: the dev client's
// "dev" build version is unparseable and therefore fails open on any window.
export const HELLO = {
  type: "hello",
  version: "0.1.0",
  min_supported: "0.2.5",
} as const;

export const GATEWAY: GatewayInfo = {
  version: "0.2.3",
  channel: "stable",
  autoUpdate: true,
  port: 4111,
  lan: { exposed: false, url: null },
  tunnelUrl: null,
  updateAvailable: false,
  latestVersion: null,
  managed: false,
  operation: null,
};

// The node opens a direct room for every agent it knows, so a fixture that names agents and no
// rooms still reaches the conversation each agent page chats in.
export function directRooms(agents: Record<string, AgentNode>): Room[] {
  return Object.keys(agents).map((agent) => ({
    id: directRoomId(agent),
    name: null,
    agents: [agent],
    createdAt: 1_755_500_000,
    lastMessageAt: null,
  }));
}

export function baseTree(agents: Record<string, AgentNode> = {}): Tree {
  return { gateway: GATEWAY, agents, devices: [], rooms: directRooms(agents) };
}

export function snapshotFrame(tree: Tree): { type: "snapshot"; tree: Tree } {
  return { type: "snapshot", tree };
}

export function startingAgent(buildPhase: BuildPhase): AgentInfo {
  return {
    status: "starting",
    activityState: "idle",
    buildPhase,
    operation: null,
    booting: false,
    startedAt: null,
    services: {},
  };
}

// A roster agent in one status, with any field overridden. Alive is the shape
// most routes read; the other statuses differ only in the orb and the label.
export function agentNode(
  status: AgentStatus = "alive",
  info: Partial<AgentInfo> = {},
): AgentNode {
  return {
    info: {
      status,
      activityState: "idle",
      buildPhase: null,
      operation: null,
      booting: false,
      startedAt: status === "alive" ? "2026-08-18T08:00:00Z" : null,
      services: {},
      ...info,
    },
    notifications: { pending: [] },
  };
}

export function aliveAgentNode(): AgentNode {
  return agentNode("alive");
}

export function agentDelta(
  name: string,
  info: AgentInfo,
): Extract<Delta, { type: "agent" }> {
  return { type: "agent", name, info };
}

export function gatewayDelta(
  gateway: Partial<GatewayInfo>,
): Extract<Delta, { type: "state" }> {
  return { type: "state", scope: "gateway", value: { ...GATEWAY, ...gateway } };
}

// `open` is the connected gateway; `hello-only` never sends the snapshot, so
// the roster stays loading; `refuse` closes the socket at once, so the client
// sits in reconnecting and raises the disconnected overlay.
export type SyncMode = "open" | "hello-only" | "refuse";

export interface SyncFixture {
  agents?: Record<string, AgentNode>;
  gateway?: Partial<GatewayInfo>;
  // Defaults to one direct room per agent; a scenario that needs a group names the whole list.
  rooms?: Room[];
  devices?: DeviceInfo[];
  deltas?: Delta[];
  mode?: SyncMode;
}

export async function installSyncSocket(
  page: Page,
  fixture: SyncFixture = {},
): Promise<void> {
  const mode = fixture.mode ?? "open";
  const agents = fixture.agents ?? {};
  const tree: Tree = {
    gateway: { ...GATEWAY, ...fixture.gateway },
    agents,
    devices: fixture.devices ?? [],
    rooms: fixture.rooms ?? directRooms(agents),
  };
  await page.routeWebSocket(/\/sync/, (ws) => {
    ws.onMessage(() => undefined);
    if (mode === "refuse") {
      void ws.close();
      return;
    }
    ws.send(JSON.stringify(HELLO));
    if (mode === "hello-only") return;
    ws.send(JSON.stringify(snapshotFrame(tree)));
    for (const delta of fixture.deltas ?? []) ws.send(JSON.stringify(delta));
  });
}
