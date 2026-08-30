import { expect, type Page } from "@playwright/test";
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

// The card's only status text is the orb's accessible name; the label line
// itself renders only while an operation is in flight or a request failed.
function orbLabelled(label: string): (page: Page) => Promise<void> {
  return async (page) => {
    await expect(
      page.getByRole("img", { name: `${AGENT}: ${label}` }),
    ).toBeVisible();
  };
}

function card(
  status: AgentStatus,
  label: string,
  info: Partial<AgentInfo> = {},
): Scenario {
  return {
    state: homeState(agentNode(status, info)),
    drive: noDrive,
    settle: orbLabelled(label),
  };
}

function operationCard(
  status: AgentStatus,
  operation: AgentInfo["operation"],
  label: string,
): Scenario {
  return {
    state: homeState(agentNode(status, { operation })),
    drive: noDrive,
    settle: async (page) => {
      await orbLabelled(label)(page);
      await expect(page.getByText(label)).toBeVisible();
    },
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

function updateScreen(
  operation: GatewayOperation,
  settle: (page: Page) => Promise<void>,
): Scenario {
  return {
    state: {
      route: HOME_ROUTE,
      sync: { agents: { [AGENT]: agentNode() }, gateway: { operation } },
    },
    drive: noDrive,
    settle,
  };
}

const UPDATE_TITLE = `updating to v${LATEST_VERSION}`;

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

// The navbar pill repeats the operation's word, so the screen's own copy is
// read inside the operation body.
function operationBody(page: Page) {
  return page.locator('[data-slot="empty-content"]');
}

export const HOME: Record<string, Scenario> = {
  "home-loading": {
    state: { route: HOME_ROUTE, sync: { mode: "hello-only" } },
    drive: noDrive,
    settle: async (page) => {
      await expect(page.getByText("loading agents...")).toBeVisible();
    },
  },
  "home-one-agent": {
    state: homeState(agentNode()),
    drive: noDrive,
    settle: async (page) => {
      await orbLabelled("alive")(page);
      await expect(page.getByRole("button", { name: "page 1" })).toBeHidden();
    },
  },
  "home-many-agents": {
    state: {
      route: HOME_ROUTE,
      sync: {
        agents: Object.fromEntries(
          ROSTER.map((name) => [name, agentNode()] as const),
        ),
      },
      storage: { "vesta:last-agent": "iris" },
    },
    drive: noDrive,
    settle: async (page) => {
      await expect(
        page.getByRole("img", { name: "iris: alive" }),
      ).toBeVisible();
      await expect(page.getByRole("button", { name: "page 6" })).toBeVisible();
      await expect(page.getByRole("button", { name: "page 4" })).toHaveCSS(
        "opacity",
        "1",
      );
    },
  },
  "home-card-starting": card("starting", "waking up...", {
    buildPhase: "starting",
  }),
  "home-card-setting-up": card("setting_up", "setting up..."),
  "home-card-booting": card("alive", "waking up...", { booting: true }),
  "home-card-thinking": card("alive", "thinking", {
    activityState: "thinking",
  }),
  "home-card-restarting": card("restarting", "restarting..."),
  "home-card-rebuilding": card("rebuilding", "updating..."),
  "home-card-stopped": card("stopped", "stopped"),
  "home-card-dead": card("dead", "broken"),
  "home-card-not-found": card("not_found", "unavailable"),
  "home-card-needs-sign-in": card("not_authenticated", "needs you to sign in"),
  "home-card-unprovisioned": card("unprovisioned", "needs to be set up"),
  "home-card-backing-up": operationCard("alive", "backing_up", "backing up..."),
  "home-card-restoring": operationCard("stopped", "restoring", "restoring..."),
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
    // The island on the page being left can still carry the same line for a
    // frame, so the assertion is the card's own copy of it.
    settle: async (page) => {
      const card = page.getByRole("button", { name: `open ${AGENT}` });
      await expect(card).toBeVisible();
      await expect(card.getByText(START_REFUSED)).toBeVisible();
    },
  },
  "notifications-popover": {
    state: notificationsState(),
    drive: openNotifications,
    settle: async (page) => {
      await expect(page.getByRole("button", { name: "see all" })).toBeVisible();
    },
  },
  "notifications-dialog": {
    state: notificationsState(),
    drive: async (page) => {
      await openNotifications(page);
      await page.getByRole("button", { name: "see all" }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.getByText("earlier")).toBeVisible();
    },
  },
  "update-snapshotting": updateScreen(gatewayOperation(), async (page) => {
    await expect(page.getByText(UPDATE_TITLE)).toBeVisible();
    await expect(page.getByText("backing up your agents")).toBeVisible();
  }),
  "update-snapshotting-agent": updateScreen(
    gatewayOperation({ agent: AGENT, done: 0, total: 3 }),
    async (page) => {
      await expect(page.getByText(`backing up ${AGENT} 1/3`)).toBeVisible();
    },
  ),
  "update-applying": updateScreen(
    gatewayOperation({ phase: "applying" }),
    async (page) => {
      await expect(page.getByText(UPDATE_TITLE)).toBeVisible();
      await expect(page.getByText("installing", { exact: true })).toBeVisible();
    },
  ),
  "update-restarting": updateScreen(
    gatewayOperation({ phase: "restarting" }),
    async (page) => {
      await expect(page.getByText(UPDATE_TITLE)).toBeVisible();
      await expect(page.getByText("restarting", { exact: true })).toBeVisible();
    },
  ),
  "update-failed": updateScreen(
    gatewayOperation({
      phase: "failed",
      error: `could not download release ${LATEST_VERSION}: connection reset by peer`,
    }),
    async (page) => {
      await expect(page.getByText("update failed")).toBeVisible();
      await expect(page.getByText("connection reset by peer")).toBeVisible();
      await expect(
        operationBody(page).getByRole("button", { name: "retry" }),
      ).toBeVisible();
      await expect(
        operationBody(page).getByRole("button", { name: "dismiss" }),
      ).toBeVisible();
    },
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
    async (page) => {
      await expect(page.getByText("update failed")).toBeVisible();
      await expect(page.getByText("backup of atlas timed out")).toBeVisible();
      await expect(page.getByText("repository locked")).toBeVisible();
    },
  ),
  "gateway-restart-operation": updateScreen(
    gatewayOperation({
      kind: "restart",
      phase: "restarting",
      targetVersion: null,
    }),
    async (page) => {
      await expect(page.getByText("restarting the gateway")).toBeVisible();
      await expect(
        operationBody(page).getByText("restarting", { exact: true }),
      ).toBeVisible();
    },
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
    settle: async (page) => {
      await expect(
        page.getByText(`updated to v${LATEST_VERSION}`),
      ).toBeVisible();
    },
  },
};
