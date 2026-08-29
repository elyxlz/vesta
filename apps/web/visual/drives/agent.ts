import { expect, type Page } from "@playwright/test";
import type { AgentInfo, AgentStatus } from "@vesta/core";
import { chatRoutes, SERVICE_KEY } from "../harness/chat-fixtures";
import {
  AGENT as AGENT_NAME,
  providerRoute,
  type ProviderInfoFixture,
  type RouteFixture,
} from "../harness/http-fixtures";
import type { Scenario, ScenarioState } from "../harness/scenario-state";
import { agentNode } from "../harness/sync-fixtures";

const AGENT_ROUTE = `/agent/${AGENT_NAME}`;
const CHAT_ROUTE = `${AGENT_ROUTE}/chat`;
const SETTINGS_ROUTE = `${AGENT_ROUTE}/settings`;
const DASHBOARD_KEYS_PATH = `/agents/${AGENT_NAME}/services/dashboard/keys`;
const DASHBOARD_FRAME_PATH = `/agents/${AGENT_NAME}/dashboard/k/${SERVICE_KEY.key}/`;
const PROVIDER_PATH = `/agents/${AGENT_NAME}/provider`;
const RESTART_PATH = `/agents/${AGENT_NAME}/restart`;

const CLAUDE_PROVIDER: ProviderInfoFixture = {
  kind: "claude",
  model: "opus-latest",
  resolved_model: "claude-opus-5",
  max_context_tokens: 200000,
  authed: true,
  plan: "max",
};

const DASHBOARD_SERVICE: Partial<AgentInfo> = {
  services: { dashboard: { port: 8321, rev: 1, public: false } },
};

const RESTART_PENDING_STORAGE = {
  "vesta-restart-pending": JSON.stringify({
    state: {
      pending: {
        [AGENT_NAME]: {
          reasons: ["host-access"],
          since: "2026-08-18T08:00:00Z",
        },
      },
    },
    version: 2,
  }),
};

// A self-contained dashboard document: it asks the host for its context (the
// handshake the Dashboard frame waits for before it fades the iframe in) and
// follows the theme the host posts back.
const DASHBOARD_PAGE = `<!doctype html>
<html><head><meta charset="utf-8"><title>dashboard</title>
<style>
  :root { color-scheme: light dark; --fg: #1c1917; --card: #ffffff; --muted: #78716c; --ring: rgba(28,25,23,.08); }
  html.dark { --fg: #f5f5f4; --card: #26221f; --muted: #a8a29e; --ring: rgba(255,255,255,.08); }
  body { margin: 0; padding: 20px; font-family: system-ui, -apple-system, sans-serif; background: transparent; color: var(--fg); }
  h1 { margin: 0 0 4px; font-size: 22px; font-weight: 600; }
  p.sub { margin: 0 0 18px; color: var(--muted); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
  .card { background: var(--card); border-radius: 18px; padding: 16px; box-shadow: 0 0 0 1px var(--ring); }
  .card b { display: block; font-size: 26px; font-weight: 600; margin-bottom: 4px; }
  .card span { color: var(--muted); font-size: 12px; }
</style></head>
<body>
  <h1>good morning</h1>
  <p class="sub">tuesday, 18 august</p>
  <div class="grid">
    <div class="card"><b>24°</b><span>sunny in lisbon</span></div>
    <div class="card"><b>3</b><span>tasks due today</span></div>
    <div class="card"><b>11:00</b><span>standup with the team</span></div>
    <div class="card"><b>2</b><span>emails waiting</span></div>
  </div>
  <script>
    window.addEventListener("message", (event) => {
      const data = event.data;
      if (data && data.type === "vesta-theme") {
        document.documentElement.classList.toggle("dark", Boolean(data.dark));
      }
    });
    window.parent.postMessage({ type: "vesta-theme-request" }, "*");
  </script>
</body></html>`;

const DASHBOARD_KEY_ROUTE: RouteFixture = {
  path: DASHBOARD_KEYS_PATH,
  method: "POST",
  json: SERVICE_KEY,
};

const DASHBOARD_FRAME_ROUTE: RouteFixture = {
  path: DASHBOARD_FRAME_PATH,
  body: DASHBOARD_PAGE,
  contentType: "text/html",
};

interface AgentPageOptions {
  status?: AgentStatus;
  info?: Partial<AgentInfo>;
  route?: string;
  routes?: RouteFixture[];
  storage?: Record<string, string>;
}

// The agent page as every scenario here starts it: one roster agent, an empty
// chat history behind a live socket (so the panel renders its empty state
// instead of the loading skeleton), and no snapshots.
function agentPage(options: AgentPageOptions = {}): ScenarioState {
  return {
    route: options.route ?? AGENT_ROUTE,
    sync: {
      agents: {
        [AGENT_NAME]: agentNode(options.status ?? "alive", options.info),
      },
    },
    routes: [
      { path: `/agents/${AGENT_NAME}/backups`, method: "GET", json: [] },
      ...chatRoutes(AGENT_NAME, { events: [] }),
      ...(options.routes ?? []),
    ],
    chatSocket: { agent: AGENT_NAME, events: [] },
    storage: options.storage,
  };
}

function island(page: Page) {
  return page.getByRole("button", { name: new RegExp(`^${AGENT_NAME}, `) });
}

async function openAgentMenu(page: Page): Promise<void> {
  await page.getByRole("button", { name: "agent actions" }).click();
}

// The same action label reaches the desktop dropdown item and the drawer button.
// The settings panel stays mounted (hidden Activity) with its own copies of these
// labels, so every match is scoped to the visible menu.
async function pickAgentAction(page: Page, label: string): Promise<void> {
  await openAgentMenu(page);
  await page
    .getByText(label, { exact: true })
    .filter({ visible: true })
    .click();
}

async function expectMenuOpen(page: Page, toggleLabel: string): Promise<void> {
  await expect(
    page.getByText("Controls", { exact: true }).filter({ visible: true }),
  ).toBeVisible();
  await expect(
    page.getByText(toggleLabel, { exact: true }).filter({ visible: true }),
  ).toBeVisible();
}

async function expectDashboardEmpty(page: Page): Promise<void> {
  await expect(page.getByText("your dashboard")).toBeVisible();
}

// The empty chat's idle line: history has loaded and the panel is past its
// skeleton, so a shot never catches the loading state by timing alone.
async function expectChatEmpty(
  page: Page,
  status: AgentStatus = "alive",
): Promise<void> {
  const line =
    status === "not_authenticated"
      ? `${AGENT_NAME} needs to sign in`
      : `${AGENT_NAME} is setting things up`;
  await expect(page.getByText(line)).toBeVisible();
}

function bottomTab(page: Page, label: string) {
  return page.locator('button[aria-current="page"]', { hasText: label });
}

const providerDialog = (page: Page) =>
  page.getByRole("dialog", { name: `provider for ${AGENT_NAME}` });

async function openProviderPicker(page: Page): Promise<void> {
  await page.getByRole("button", { name: "more actions" }).click();
  await page.getByRole("menuitem", { name: "switch provider" }).click();
  await expect(providerDialog(page)).toBeVisible();
}

// Walk the picker through OpenRouter to the submit: key, then the top model
// the catalog preselects, which is where OpenRouter finishes.
async function submitOpenRouter(page: Page): Promise<void> {
  const dialog = providerDialog(page);
  await dialog.getByText("OpenRouter", { exact: true }).click();
  await dialog.getByPlaceholder("sk-or-v1-...").fill("sk-or-v1-visual");
  await dialog.getByRole("button", { name: "next" }).click();
  await expect(dialog.getByText("Claude Sonnet 5")).toBeVisible();
  await dialog.getByRole("button", { name: "continue" }).click();
}

function providerModal(routes: RouteFixture[]): ScenarioState {
  return agentPage({
    route: SETTINGS_ROUTE,
    routes: [providerRoute(CLAUDE_PROVIDER), ...routes],
  });
}

export const AGENT: Record<string, Scenario> = {
  "agent-dashboard-empty": {
    state: agentPage(),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expectDashboardEmpty(page);
      await expectChatEmpty(page);
    },
  },
  "agent-dashboard-unavailable": {
    state: agentPage({
      info: DASHBOARD_SERVICE,
      routes: [
        {
          path: DASHBOARD_KEYS_PATH,
          method: "POST",
          status: 500,
          json: { error: "dashboard is not registered" },
        },
      ],
    }),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByText("dashboard unavailable")).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "agent-dashboard-live": {
    state: agentPage({
      info: DASHBOARD_SERVICE,
      routes: [DASHBOARD_KEY_ROUTE, DASHBOARD_FRAME_ROUTE],
    }),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.locator("iframe")).toHaveClass(/opacity-100/);
      await expect(
        page.frameLocator("iframe").getByText("good morning"),
      ).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "agent-chat-collapsed": {
    state: agentPage(),
    drive: async (page) => {
      await expectChatEmpty(page);
      await page.locator("button:has(svg.lucide-panel-right-close)").click();
    },
    settle: async (page) => {
      await expectDashboardEmpty(page);
      await expect(
        page.getByRole("button", { name: "chat", exact: true }),
      ).toBeVisible();
      await expect(page.getByPlaceholder(`message ${AGENT_NAME}`)).toBeHidden();
    },
  },
  "agent-navbar-needs-auth": {
    state: agentPage({ status: "not_authenticated" }),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("button", {
          name: `${AGENT_NAME}, needs you to sign in`,
        }),
      ).toBeVisible();
      await expectChatEmpty(page, "not_authenticated");
      await expect(
        page.getByRole("button", { name: "sign in", exact: true }),
      ).toBeVisible();
    },
  },
  "agent-navbar-restart-pending": {
    state: agentPage({ storage: RESTART_PENDING_STORAGE }),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "restart to apply changes" }),
      ).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "agent-island-collapsed": {
    state: agentPage(),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: `${AGENT_NAME}, alive` }),
      ).toBeVisible();
      await expectDashboardEmpty(page);
      await expectChatEmpty(page);
    },
  },
  "agent-island-error": {
    state: agentPage({
      routes: [
        {
          path: RESTART_PATH,
          method: "POST",
          status: 500,
          json: { error: "container failed to restart" },
        },
      ],
    }),
    drive: (page) => pickAgentAction(page, "restart"),
    settle: async (page) => {
      await expect(
        island(page).getByText("container failed to restart").first(),
      ).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "agent-island-expanded": {
    state: agentPage({ routes: [providerRoute(CLAUDE_PROVIDER)] }),
    drive: (page) => island(page).click(),
    settle: async (page) => {
      await expect(page.getByText("Claude · Opus 5")).toBeVisible();
      await expect(page.getByText("alive", { exact: true })).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "agent-menu-desktop": {
    state: agentPage(),
    drive: openAgentMenu,
    settle: async (page) => {
      await expectMenuOpen(page, "stop");
      await expectChatEmpty(page);
    },
  },
  "agent-menu-stopped": {
    state: agentPage({ status: "stopped" }),
    drive: openAgentMenu,
    settle: async (page) => {
      await expectMenuOpen(page, "start");
      // A stopped agent has no chat socket to seed from: its panel keeps the skeleton.
      await expect(page.locator(".animate-pulse").first()).toBeVisible();
    },
  },
  "agent-menu-mobile": {
    state: agentPage(),
    drive: openAgentMenu,
    settle: async (page) => {
      await expectMenuOpen(page, "stop");
      await expect(
        page.getByRole("button", { name: "switch provider" }),
      ).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "mobile-navbar-dashboard": {
    state: agentPage(),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(bottomTab(page, "dashboard").first()).toBeVisible();
      await expectDashboardEmpty(page);
      await expectChatEmpty(page);
    },
  },
  "mobile-navbar-chat": {
    state: agentPage({ route: CHAT_ROUTE }),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(bottomTab(page, "chat").first()).toBeVisible();
      await expect(
        page.getByPlaceholder(`message ${AGENT_NAME}`),
      ).toBeVisible();
      await expectChatEmpty(page);
    },
  },
  "modal-provider-picker": {
    state: providerModal([]),
    drive: openProviderPicker,
    settle: async (page) => {
      const dialog = providerDialog(page);
      await expect(dialog.getByText("how should it run?")).toBeVisible();
      await expect(
        dialog.getByText("OpenRouter", { exact: true }),
      ).toBeVisible();
    },
  },
  "modal-provider-submitting": {
    state: providerModal([{ path: PROVIDER_PATH, method: "PUT", hang: true }]),
    drive: async (page) => {
      await openProviderPicker(page);
      await submitOpenRouter(page);
    },
    settle: async (page) => {
      await expect(
        providerDialog(page).getByText("applying new provider config..."),
      ).toBeVisible();
    },
  },
  "modal-provider-error": {
    state: providerModal([
      {
        path: PROVIDER_PATH,
        method: "PUT",
        status: 500,
        json: { error: "the agent refused the new provider" },
      },
    ]),
    drive: async (page) => {
      await openProviderPicker(page);
      await submitOpenRouter(page);
    },
    settle: async (page) => {
      const dialog = providerDialog(page);
      await expect(
        dialog.getByText("the agent refused the new provider"),
      ).toBeVisible();
      await expect(dialog.getByText("how should it run?")).toBeVisible();
    },
  },
  "modal-delete-confirm": {
    state: agentPage({ route: SETTINGS_ROUTE }),
    drive: async (page) => {
      await page.getByRole("button", { name: "delete", exact: true }).click();
    },
    settle: async (page) => {
      const dialog = page.getByRole("alertdialog", {
        name: `delete ${AGENT_NAME}?`,
      });
      await expect(dialog).toBeVisible();
      await expect(
        dialog.getByRole("button", { name: "cancel" }),
      ).toBeVisible();
    },
  },
};
