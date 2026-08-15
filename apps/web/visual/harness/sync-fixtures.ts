import type { Page } from "@playwright/test";
import type {
  AgentInfo,
  AgentNode,
  BuildPhase,
  Delta,
  Tree,
} from "@vesta/core";

// Version pair mirrors the locked sync-protocol.json fixture: the dev client's
// "dev" build version is unparseable and therefore fails open on any window.
export const HELLO = {
  type: "hello",
  version: "0.1.0",
  min_supported: "0.1.189",
} as const;

export function baseTree(agents: Record<string, AgentNode> = {}): Tree {
  return {
    gateway: {
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
    },
    agents,
    devices: [],
  };
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

export function agentDelta(
  name: string,
  info: AgentInfo,
): Extract<Delta, { type: "agent" }> {
  return { type: "agent", name, info };
}

export async function installSyncSocket(
  page: Page,
  deltas: Delta[],
): Promise<void> {
  await page.routeWebSocket(/\/sync/, (ws) => {
    ws.onMessage(() => undefined);
    ws.send(JSON.stringify(HELLO));
    ws.send(JSON.stringify(snapshotFrame(baseTree())));
    for (const delta of deltas) ws.send(JSON.stringify(delta));
  });
}
