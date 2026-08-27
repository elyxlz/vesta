import { expect, type Page } from "@playwright/test";
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

function whatsNew(
  releases: RouteFixture,
  settle: Scenario["settle"],
): Scenario {
  return {
    state: settingsState({ routes: [releases] }),
    drive: openWhatsNew,
    settle,
  };
}

// The desktop app leads with the hosted account card; the connect-link form is
// one click behind it. Web renders the form directly.
async function toLinkForm(page: Page): Promise<void> {
  const selfHost = page.getByRole("button", {
    name: "self-hosting? connect with a link",
  });
  const linkInput = page.getByPlaceholder("paste your connect link");
  await expect(linkInput.or(selfHost).first()).toBeVisible();
  if (await selfHost.isVisible()) await selfHost.click();
  await expect(linkInput).toBeVisible();
}

async function submitLink(page: Page): Promise<void> {
  await toLinkForm(page);
  await page
    .getByPlaceholder("paste your connect link")
    .fill("http://vestad.local/app#k=visual-api-key");
  await page.getByRole("button", { name: "connect", exact: true }).click();
}

const SIGNED_OUT: ScenarioState = { route: "/connect", connection: false };

export const APP_SETTINGS: Record<string, Scenario> = {
  "app-settings": {
    state: settingsState(),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("heading", { name: "app settings" }),
      ).toBeVisible();
      await expect(page.getByText("lan access")).toBeVisible();
      await expect(page.getByText("remote access")).toBeVisible();
    },
  },
  "app-settings-managed": {
    state: settingsState({ sync: { gateway: { managed: true } } }),
    drive: (page) => scrollTo(page, "manage account & billing"),
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "manage account & billing" }),
      ).toBeVisible();
    },
  },
  "app-settings-devices": {
    state: settingsState({ sync: { devices: DEVICES } }),
    drive: (page) => scrollTo(page, "share this device's location"),
    settle: async (page) => {
      await expect(page.getByText("present now")).toBeVisible();
      await expect(page.getByText("last seen 3h ago")).toBeVisible();
      await expect(page.getByText("last seen 12m ago")).toBeVisible();
      await expect(
        page.getByText("Lisbon, Portugal · Europe/Lisbon"),
      ).toBeVisible();
      await expect(
        page.getByText("share this device's location"),
      ).toBeVisible();
    },
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
    settle: async (page) => {
      await expect(page.getByText(LAN_URL)).toBeVisible();
      await expect(page.getByText(TUNNEL_URL)).toBeVisible();
    },
  },
  "app-settings-check-updates": {
    state: settingsState({
      routes: [{ path: "/version/check", method: "POST", hang: true }],
    }),
    drive: async (page) => {
      await scrollTo(page, "check for updates");
      await page.getByRole("button", { name: "check for updates" }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "check for updates" }),
      ).toBeDisabled();
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
      page.getByText("Vesta Desktop", { exact: true }).scrollIntoViewIfNeeded(),
    settle: async (page) => {
      await expect(page.getByText("Vesta gateway")).toBeVisible();
      // Both rows expose an "update" action (Vesta Desktop and the gateway pill).
      await expect(
        page.getByRole("button", { name: "update", exact: true }),
      ).toHaveCount(2);
    },
  },
  "app-settings-restart-dialog": {
    state: settingsState(),
    drive: async (page) => {
      await page.getByRole("button", { name: "restart", exact: true }).click();
    },
    settle: async (page) => {
      const dialog = page.getByRole("alertdialog");
      await expect(dialog.getByText("restart the gateway?")).toBeVisible();
      await expect(
        dialog.getByRole("button", { name: "cancel" }),
      ).toBeVisible();
    },
  },
  "app-settings-gateway-logs": {
    state: settingsState({ routes: [GATEWAY_LOGS_ROUTE] }),
    drive: async (page) => {
      await page.getByRole("button", { name: "view logs" }).click();
    },
    settle: async (page) => {
      const dialog = page.getByRole("dialog", { name: "Gateway logs" });
      await expect(dialog.getByText("listening on 0.0.0.0:4111")).toBeVisible();
      await expect(dialog.getByText("client web focused")).toBeVisible();
    },
  },
  "whats-new-loading": whatsNew(
    { path: RELEASES_URL, hang: true },
    async (page) => {
      const dialog = page.getByRole("dialog", { name: "What's new" });
      await expect(dialog.getByRole("status")).toBeVisible();
    },
  ),
  "whats-new-error": whatsNew(
    { path: RELEASES_URL, status: 500, json: { message: "rate limited" } },
    async (page) => {
      await expect(page.getByText("Couldn't load release notes")).toBeVisible();
    },
  ),
  "whats-new-notes": whatsNew(
    { path: RELEASES_URL, json: RELEASES },
    async (page) => {
      const dialog = page.getByRole("dialog", { name: "What's new" });
      await expect(dialog.getByText("v0.2.3")).toBeVisible();
      await expect(dialog.getByText("v0.2.2")).toBeVisible();
      await expect(
        dialog.getByText("faster reconnects after a gateway restart", {
          exact: false,
        }),
      ).toBeVisible();
    },
  ),
  "connect-form": {
    state: SIGNED_OUT,
    drive: toLinkForm,
    settle: async (page) => {
      await expect(
        page.getByPlaceholder("paste your connect link"),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "connect", exact: true }),
      ).toBeVisible();
    },
  },
  "connect-connecting": {
    state: { ...SIGNED_OUT, routes: [{ path: "/health", hang: true }] },
    drive: submitLink,
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "connecting..." }),
      ).toBeDisabled();
    },
  },
  "connect-error": {
    state: { ...SIGNED_OUT, routes: [{ path: "/health", status: 503 }] },
    drive: submitLink,
    settle: async (page) => {
      await expect(page.getByRole("alert")).toHaveText(
        "could not reach server",
      );
    },
  },
  "connect-managed-desktop": {
    state: SIGNED_OUT,
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "continue with vesta account" }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "self-hosting? connect with a link" }),
      ).toBeVisible();
    },
  },
  "callback-error": {
    state: { route: "/cb", connection: false },
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByText("missing code")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "back to sign-in" }),
      ).toBeVisible();
    },
  },
  "disconnected-overlay": {
    state: { route: "/", sync: { mode: "refuse" } },
    drive: () => Promise.resolve(),
    settle: async (page) => {
      const overlay = page.getByRole("alertdialog", {
        name: "disconnected from gateway",
      });
      await expect(
        overlay.getByText("attempting to reconnect to vestad.local..."),
      ).toBeVisible();
    },
  },
  "debug-page": {
    state: { route: "/debug" },
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(
        page.getByRole("heading", { name: "orb states" }),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", { name: "chat bubbles" }),
      ).toBeVisible();
    },
  },
  "keybinds-windows": {
    state: { ...settingsState(), native: { platform: "win32" } },
    drive: (page) =>
      page.getByText("keybinds", { exact: true }).scrollIntoViewIfNeeded(),
    settle: async (page) => {
      await expect(page.getByText("Ctrl").first()).toBeVisible();
    },
  },
};
