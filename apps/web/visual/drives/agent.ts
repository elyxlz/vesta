import { type Page } from "@playwright/test";
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

const providerDialog = (page: Page) =>
  page.getByRole("dialog", { name: `provider for ${AGENT_NAME}` });

async function openProviderPicker(page: Page): Promise<void> {
  await page.getByRole("tab", { name: "provider", exact: true }).click();
  await page.getByRole("button", { name: "change provider" }).click();
}

// Walk the picker through OpenRouter to the submit: key, then the top model
// the catalog preselects, which is where OpenRouter finishes.
async function submitOpenRouter(page: Page): Promise<void> {
  const dialog = providerDialog(page);
  await dialog.getByText("OpenRouter", { exact: true }).click();
  await dialog.getByPlaceholder("sk-or-v1-...").fill("sk-or-v1-visual");
  await dialog.getByRole("button", { name: "next" }).click();
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
  },
  "agent-dashboard-live": {
    state: agentPage({
      info: DASHBOARD_SERVICE,
      routes: [DASHBOARD_KEY_ROUTE, DASHBOARD_FRAME_ROUTE],
    }),
    drive: () => Promise.resolve(),
  },
  "agent-chat-collapsed": {
    state: agentPage(),
    drive: async (page) => {
      await page.locator("button:has(svg.lucide-panel-right-close)").click();
    },
  },
  "agent-navbar-needs-auth": {
    state: agentPage({ status: "not_authenticated" }),
    drive: () => Promise.resolve(),
  },
  "agent-navbar-restart-pending": {
    state: agentPage({ storage: RESTART_PENDING_STORAGE }),
    drive: () => Promise.resolve(),
  },
  "agent-island-collapsed": {
    state: agentPage(),
    drive: () => Promise.resolve(),
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
  },
  "agent-island-expanded": {
    state: agentPage({ routes: [providerRoute(CLAUDE_PROVIDER)] }),
    drive: (page) => island(page).click(),
  },
  "agent-menu-desktop": {
    state: agentPage(),
    drive: openAgentMenu,
  },
  "agent-menu-stopped": {
    state: agentPage({ status: "stopped" }),
    drive: openAgentMenu,
  },
  "agent-menu-mobile": {
    state: agentPage(),
    drive: openAgentMenu,
  },
  "mobile-navbar-dashboard": {
    state: agentPage(),
    drive: () => Promise.resolve(),
  },
  "mobile-navbar-chat": {
    state: agentPage({ route: CHAT_ROUTE }),
    drive: () => Promise.resolve(),
  },
  "modal-provider-picker": {
    state: providerModal([]),
    drive: openProviderPicker,
  },
  "modal-provider-submitting": {
    state: providerModal([{ path: PROVIDER_PATH, method: "PUT", hang: true }]),
    drive: async (page) => {
      await openProviderPicker(page);
      await submitOpenRouter(page);
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
  },
  "modal-delete-confirm": {
    state: agentPage({ route: SETTINGS_ROUTE }),
    drive: async (page) => {
      await page
        .getByRole("button", { name: `delete ${AGENT_NAME}`, exact: true })
        .click();
    },
  },
};
