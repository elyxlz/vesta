import { type Page } from "@playwright/test";
import type { DeviceInfo } from "@vesta/core";
import { AGENT, type RouteFixture } from "../harness/http-fixtures";
import {
  FIXED_TIME,
  type Scenario,
  type ScenarioState,
} from "../harness/scenario-state";
import { aliveAgentNode, type SyncFixture } from "../harness/sync-fixtures";

// Small DTOs duplicated from src/api/gateway.ts (the app tsconfig project):
// GET /gateway/info and GET /gateway/settings, both read by the settings page.
interface GatewayInfoFixture {
  lan: { exposed: boolean; url: string | null };
  tunnel_url: string | null;
  port: number;
}

interface GatewaySettingsFixture {
  auto_update: boolean;
  user_context: boolean;
  channel: "stable" | "beta";
  auto_backup: {
    enabled: boolean;
    every_n_days: number;
    retention: { periodic: number; pre_update_versions: number };
  };
}

const GATEWAY_INFO: GatewayInfoFixture = {
  lan: { exposed: false, url: null },
  tunnel_url: null,
  port: 4111,
};

const LAN_URL = "http://192.168.1.20:4111";
const TUNNEL_URL = "https://luna-gateway.example-tunnel.com";

const GATEWAY_INFO_EXPOSED: GatewayInfoFixture = {
  lan: { exposed: true, url: LAN_URL },
  tunnel_url: TUNNEL_URL,
  port: 4111,
};

const GATEWAY_SETTINGS: GatewaySettingsFixture = {
  auto_update: true,
  user_context: true,
  channel: "stable",
  auto_backup: {
    enabled: true,
    every_n_days: 1,
    retention: { periodic: 1, pre_update_versions: 5 },
  },
};

const RELEASES_URL = "https://api.github.com/repos/elyxlz/vesta/releases";

// The GitHub release list the What's new dialog parses: only the fields the
// parser reads, with the whats-new markers release.sh writes into each body.
const RELEASES = [
  {
    tag_name: "v0.2.3",
    published_at: "2026-08-14T09:00:00Z",
    prerelease: false,
    body: [
      "<!-- whats-new -->",
      "- the devices card in app settings lists every signed-in device",
      "- a gateway logs viewer with a follow tail",
      "<!-- /whats-new -->",
      "",
      "## Migrations",
      "- 0042-devices-card.md",
    ].join("\n"),
  },
  {
    tag_name: "v0.2.2",
    published_at: "2026-08-07T09:00:00Z",
    prerelease: false,
    body: [
      "<!-- whats-new -->",
      "faster reconnects after a gateway restart, and this What's new dialog.",
      "<!-- /whats-new -->",
    ].join("\n"),
  },
];

const GATEWAY_LOG_LINES = [
  "2026-08-18T09:58:12.301Z  INFO  vestad::serve: listening on 0.0.0.0:4111",
  "2026-08-18T09:58:12.418Z  INFO  vestad::docker: reconciling 1 container",
  "2026-08-18T09:58:13.002Z  INFO  vestad::docker: agent luna is running",
  "2026-08-18T09:58:40.771Z  WARN  vestad::update: release check skipped, no network",
  "2026-08-18T09:59:02.115Z  ERROR  vestad::agent_status: tap for luna closed: connection reset by peer",
  "2026-08-18T09:59:03.120Z  INFO  vestad::agent_status: tap for luna reconnected",
  "2026-08-18T09:59:58.900Z  DEBUG  vestad::sync: client web focused",
];

const GATEWAY_LOGS_ROUTE: RouteFixture = {
  path: "/gateway/logs",
  method: "GET",
  contentType: "text/event-stream",
  body: GATEWAY_LOG_LINES.map((line) => `data: ${line}\n\n`).join(""),
};

function gatewayRoutes(
  info: GatewayInfoFixture = GATEWAY_INFO,
): RouteFixture[] {
  return [
    { path: "/gateway/info", method: "GET", json: info },
    { path: "/gateway/settings", method: "GET", json: GATEWAY_SETTINGS },
  ];
}

// The settings page needs one roster agent (an empty fetched roster redirects
// to /new) and both gateway setup answers (the setup rows hide otherwise).
function settingsState(
  overrides: { sync?: SyncFixture; routes?: RouteFixture[] } = {},
): ScenarioState {
  return {
    route: "/settings",
    sync: { agents: { [AGENT]: aliveAgentNode() }, ...overrides.sync },
    routes: [...gatewayRoutes(), ...(overrides.routes ?? [])],
  };
}

function minutesAgo(minutes: number): string {
  return new Date(FIXED_TIME.getTime() - minutes * 60_000).toISOString();
}

const DEVICES: DeviceInfo[] = [
  {
    id: "device-macbook",
    kind: "desktop",
    descriptor: "Emilio's MacBook Pro",
    present: true,
    lastSeen: minutesAgo(0),
    pushEnabled: false,
    timezone: "Europe/Rome",
    position: null,
    positionAt: null,
  },
  {
    id: "device-chrome",
    kind: "web",
    descriptor: "Chrome on Windows",
    present: false,
    lastSeen: minutesAgo(3 * 60 + 5),
    pushEnabled: false,
    timezone: "Europe/London",
    position: null,
    positionAt: null,
  },
  {
    id: "device-iphone",
    kind: "mobile",
    descriptor: "Emilio's iPhone",
    present: false,
    lastSeen: minutesAgo(12),
    pushEnabled: true,
    timezone: "Europe/Lisbon",
    position: {
      latitude: 38.7223,
      longitude: -9.1393,
      accuracyM: 25,
      place: { city: "Lisbon", region: "Lisboa", country: "Portugal" },
    },
    positionAt: minutesAgo(12),
  },
];

// The lower cards sit below the fold at every viewport, so a shot of one of
// them scrolls it into view first.
async function scrollTo(page: Page, text: string): Promise<void> {
  await page.getByText(text).scrollIntoViewIfNeeded();
}

async function openWhatsNew(page: Page): Promise<void> {
  await page.getByRole("button", { name: "What's new" }).click();
}

function whatsNew(releases: RouteFixture): Scenario {
  return {
    state: settingsState({ routes: [releases] }),
    drive: openWhatsNew,
  };
}

// The desktop app leads with the hosted account card; the connect-link form is
// one click behind it. Web renders the form directly.
async function toLinkForm(page: Page): Promise<void> {
  const selfHost = page.getByRole("button", {
    name: "self-hosting? connect with a link",
  });
  const linkInput = page.getByPlaceholder("paste your connect link");
  await linkInput.or(selfHost).first().waitFor({ state: "visible" });
  if (await selfHost.isVisible()) await selfHost.click();
}

async function submitLink(page: Page): Promise<void> {
  await toLinkForm(page);
  await page
    .getByPlaceholder("paste your connect link")
    .fill("http://vestad.local/app#k=visual-api-key");
  await page.getByRole("button", { name: "connect", exact: true }).click();
}

const SIGNED_OUT: ScenarioState = { route: "/connect", connection: false };

const RECENT_GATEWAYS = [
  {
    id: "gateway-luna",
    url: "https://luna.example.com",
    hosted: false,
    lastConnectedAt: FIXED_TIME.getTime(),
    connection: {
      url: "https://luna.example.com",
      accessToken: "visual-access-token",
      refreshToken: "visual-refresh-token",
      expiresAt: FIXED_TIME.getTime() + 3_600_000,
    },
  },
  {
    id: "gateway-home",
    url: "https://home.example.com",
    hosted: false,
    lastConnectedAt: FIXED_TIME.getTime() - 86_400_000,
    connection: {
      url: "https://home.example.com",
      accessToken: "visual-access-token",
      refreshToken: "visual-refresh-token",
      expiresAt: FIXED_TIME.getTime() + 3_600_000,
    },
  },
];

export const APP_SETTINGS: Record<string, Scenario> = {
  "app-settings": {
    state: settingsState(),
    drive: () => Promise.resolve(),
  },
  "app-settings-managed": {
    state: settingsState({ sync: { gateway: { managed: true } } }),
    drive: (page) => scrollTo(page, "manage account & billing"),
  },
  "app-settings-devices": {
    state: settingsState({ sync: { devices: DEVICES } }),
    drive: (page) => scrollTo(page, "share this device's location"),
  },
  "app-settings-lan-tunnel": {
    state: {
      route: "/settings",
      sync: {
        agents: { [AGENT]: aliveAgentNode() },
        gateway: {
          lan: { exposed: true, url: LAN_URL },
          tunnelUrl: TUNNEL_URL,
        },
      },
      routes: gatewayRoutes(GATEWAY_INFO_EXPOSED),
    },
    drive: (page) => scrollTo(page, "remote access"),
  },
  "app-settings-check-updates": {
    state: settingsState({
      routes: [{ path: "/version/check", method: "POST", hang: true }],
    }),
    drive: async (page) => {
      await scrollTo(page, "check for updates");
      await page.getByRole("button", { name: "check for updates" }).click();
    },
  },
  "app-settings-updates": {
    state: {
      ...settingsState({
        sync: { gateway: { updateAvailable: true, latestVersion: "0.2.11" } },
      }),
      native: { appUpdate: { available: true, version: "0.2.11" } },
    },
    drive: (page) =>
      page.getByText("Vesta desktop", { exact: true }).scrollIntoViewIfNeeded(),
  },
  "app-settings-restart-dialog": {
    state: settingsState(),
    drive: async (page) => {
      await page.getByRole("button", { name: "restart", exact: true }).click();
    },
  },
  "app-settings-gateway-logs": {
    state: settingsState({ routes: [GATEWAY_LOGS_ROUTE] }),
    drive: async (page) => {
      await page.getByRole("button", { name: "view logs" }).click();
    },
  },
  "whats-new-loading": whatsNew({ path: RELEASES_URL, hang: true }),
  "whats-new-error": whatsNew({
    path: RELEASES_URL,
    status: 500,
    json: { message: "rate limited" },
  }),
  "whats-new-notes": whatsNew({ path: RELEASES_URL, json: RELEASES }),
  "connect-form": {
    state: SIGNED_OUT,
    drive: toLinkForm,
  },
  "connect-recent-gateways": {
    state: {
      ...SIGNED_OUT,
      storage: {
        "vesta-recent-gateways": JSON.stringify(RECENT_GATEWAYS),
      },
    },
    drive: async (page) => {
      const trigger = page.getByRole("button", { name: "recent gateways" });
      await trigger.click();
    },
  },
  "connect-connecting": {
    state: { ...SIGNED_OUT, routes: [{ path: "/health", hang: true }] },
    drive: submitLink,
  },
  "connect-error": {
    state: { ...SIGNED_OUT, routes: [{ path: "/health", status: 503 }] },
    drive: submitLink,
  },
  "connect-managed-desktop": {
    state: SIGNED_OUT,
    drive: () => Promise.resolve(),
  },
  "callback-error": {
    state: { route: "/cb", connection: false },
    drive: () => Promise.resolve(),
  },
  "disconnected-overlay": {
    state: { route: "/", sync: { mode: "refuse" } },
    drive: () => Promise.resolve(),
  },
  "debug-page": {
    state: { route: "/debug" },
    drive: () => Promise.resolve(),
  },
  "keybinds-windows": {
    state: { ...settingsState(), native: { platform: "win32" } },
    drive: (page) =>
      page.getByText("keybinds", { exact: true }).scrollIntoViewIfNeeded(),
  },
};
