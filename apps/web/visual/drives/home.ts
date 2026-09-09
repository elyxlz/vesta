import { type Page } from "@playwright/test";
import type {
  AgentInfo,
  AgentNode,
  AgentStatus,
  GatewayOperation,
} from "@vesta/core";
import { AGENT } from "../harness/http-fixtures";
import {
  FIXED_TIME,
  type Scenario,
  type ScenarioState,
} from "../harness/scenario-state";
import { agentNode, gatewayDelta } from "../harness/sync-fixtures";

const HOME_ROUTE = "/";
const LATEST_VERSION = "0.2.4";
const ROSTER = ["luna", "nova", "atlas", "iris", "sol", "vesper"];
const START_REFUSED = `gateway refused to start ${AGENT}: disk is full`;

function homeState(agent: AgentNode): ScenarioState {
  return { route: HOME_ROUTE, sync: { agents: { [AGENT]: agent } } };
}

const noDrive = (): Promise<void> => Promise.resolve();

function card(status: AgentStatus, info: Partial<AgentInfo> = {}): Scenario {
  return {
    state: homeState(agentNode(status, info)),
    drive: noDrive,
  };
}

function operationCard(
  status: AgentStatus,
  operation: AgentInfo["operation"],
): Scenario {
  return {
    state: homeState(agentNode(status, { operation })),
    drive: noDrive,
  };
}

function gatewayOperation(
  overrides: Partial<GatewayOperation> = {},
): GatewayOperation {
  return {
    kind: "update",
    phase: "snapshotting",
    agent: null,
    done: null,
    total: null,
    targetVersion: LATEST_VERSION,
    warnings: [],
    error: null,
    ...overrides,
  };
}

function updateScreen(operation: GatewayOperation): Scenario {
  return {
    state: {
      route: HOME_ROUTE,
      sync: { agents: { [AGENT]: agentNode() }, gateway: { operation } },
    },
    drive: noDrive,
  };
}

// The notification history, both surfaces: the bell's popover taster and the
// "see all" dialog over the same log. The watermark sits between entry 4 and
// 3, so three rows are unseen and the dialog carries the new/earlier split.
const NOTIFICATIONS_SEEN_AT = FIXED_TIME.getTime() / 1000 - 5400;
const NEWEST_NOTIFICATION_AT = NOTIFICATIONS_SEEN_AT + 5100;
const LOGGED_NOTIFICATIONS = [
  {
    id: 6,
    at: NEWEST_NOTIFICATION_AT,
    agent: AGENT,
    kind: "message",
    title: AGENT,
    body: "the flight to lisbon moved to 6:40am, so i pushed the taxi to 4:15 and told the hotel you land early. the boarding pass is in your email.",
  },
  {
    id: 5,
    at: NOTIFICATIONS_SEEN_AT + 3300,
    agent: AGENT,
    kind: "task",
    title: AGENT,
    body: "finished the quarterly expense report and filed it. two receipts were missing, so i flagged them in the sheet for you.",
  },
  {
    id: 4,
    at: NOTIFICATIONS_SEEN_AT + 900,
    agent: AGENT,
    kind: "needs_user",
    title: AGENT,
    body: "the calendar sign-in expired, so i cannot read your week. sign in again when you have a minute.",
  },
  {
    id: 3,
    at: NOTIFICATIONS_SEEN_AT - 1800,
    agent: "",
    kind: "update_available",
    title: "Vesta",
    body: `version ${LATEST_VERSION} is ready to install`,
  },
  {
    id: 2,
    at: NOTIFICATIONS_SEEN_AT - 7200,
    agent: AGENT,
    kind: "message",
    title: AGENT,
    body: "your mother called while you were in the review. she asked about sunday lunch and i said you would call back tonight.",
  },
  {
    id: 1,
    at: NOTIFICATIONS_SEEN_AT - 90000,
    agent: AGENT,
    kind: "agent_status",
    title: AGENT,
    body: "recovered and back online",
  },
];

function notificationsState(): ScenarioState {
  return {
    route: HOME_ROUTE,
    sync: {
      agents: { [AGENT]: agentNode() },
      gateway: {
        userNotificationsSeenAt: NOTIFICATIONS_SEEN_AT,
        lastUserNotificationAt: NEWEST_NOTIFICATION_AT,
      },
    },
    routes: [
      {
        path: "/notifications",
        method: "GET",
        json: { notifications: LOGGED_NOTIFICATIONS },
      },
    ],
  };
}

function openNotifications(page: Page): Promise<void> {
  return page.getByRole("button", { name: "notifications" }).click();
}

export const HOME: Record<string, Scenario> = {
  "home-loading": {
    state: { route: HOME_ROUTE, sync: { mode: "hello-only" } },
    drive: noDrive,
  },
  "home-one-agent": {
    state: homeState(agentNode()),
    drive: noDrive,
  },
  "home-many-agents": {
    state: {
      route: HOME_ROUTE,
      sync: {
        agents: Object.fromEntries(
          ROSTER.map((name) => [name, agentNode()] as const),
        ),
      },
      storage: {
        "vesta-preferences": JSON.stringify({
          state: { lastAgent: "iris" },
          version: 1,
        }),
      },
    },
    drive: noDrive,
  },
  "home-card-starting": card("starting", {
    buildPhase: "starting",
  }),
  "home-card-setting-up": card("setting_up"),
  "home-card-booting": card("alive", { booting: true }),
  "home-card-thinking": card("alive", {
    activityState: "thinking",
  }),
  "home-card-restarting": card("restarting"),
  "home-card-rebuilding": card("rebuilding"),
  "home-card-stopped": card("stopped"),
  "home-card-dead": card("dead"),
  "home-card-not-found": card("not_found"),
  "home-card-needs-sign-in": card("not_authenticated"),
  "home-card-unprovisioned": card("unprovisioned"),
  "home-card-backing-up": operationCard("alive", "backing_up"),
  "home-card-restoring": operationCard("stopped", "restoring"),
  "home-card-start-failed": {
    state: {
      route: `/agent/${AGENT}`,
      sync: { agents: { [AGENT]: agentNode("stopped") } },
      routes: [
        {
          path: `/agents/${AGENT}/start`,
          method: "POST",
          status: 500,
          json: { error: START_REFUSED },
        },
      ],
    },
    // The failure is this client's own op state, so it is raised on the agent
    // page and carried home in memory rather than reloaded.
    drive: async (page) => {
      await page.getByRole("button", { name: "agent actions" }).click();
      await page
        .getByText("start", { exact: true })
        .filter({ visible: true })
        .click();
      await page.getByRole("button", { name: "home", exact: true }).click();
    },
  },
  "notifications-popover": {
    state: notificationsState(),
    drive: openNotifications,
  },
  "notifications-dialog": {
    state: notificationsState(),
    drive: async (page) => {
      await openNotifications(page);
      await page.getByRole("button", { name: "see all" }).click();
    },
  },
  "update-snapshotting": updateScreen(gatewayOperation()),
  "update-snapshotting-agent": updateScreen(
    gatewayOperation({ agent: AGENT, done: 0, total: 3 }),
  ),
  "update-applying": updateScreen(gatewayOperation({ phase: "applying" })),
  "update-restarting": updateScreen(gatewayOperation({ phase: "restarting" })),
  "update-failed": updateScreen(
    gatewayOperation({
      phase: "failed",
      error: `could not download release ${LATEST_VERSION}: connection reset by peer`,
    }),
  ),
  "update-warnings": updateScreen(
    gatewayOperation({
      phase: "failed",
      error: "the gateway restart did not complete in time",
      warnings: [
        "backup of atlas timed out after 10m, skipped",
        "backup of sol failed: repository locked",
      ],
    }),
  ),
  "gateway-restart-operation": updateScreen(
    gatewayOperation({
      kind: "restart",
      phase: "restarting",
      targetVersion: null,
    }),
  ),
  // The snapshot carries the running update; the delta clears it against the
  // new version, which is the resolution the notice reports.
  "updated-to": {
    state: {
      route: HOME_ROUTE,
      sync: {
        agents: { [AGENT]: agentNode() },
        gateway: { operation: gatewayOperation({ phase: "restarting" }) },
        deltas: [gatewayDelta({ operation: null, version: LATEST_VERSION })],
      },
    },
    drive: noDrive,
  },
};
