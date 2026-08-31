import { expect, type Page } from "@playwright/test";
import type {
  AgentNode,
  NotificationEvent,
  ProviderCatalog,
} from "@vesta/core";
import { chatRoutes } from "../harness/chat-fixtures";
import {
  AGENT,
  CLAUDE_MODELS,
  PROVIDER_CATALOG,
  providerRoute,
  type ProviderInfoFixture,
  type RouteFixture,
} from "../harness/http-fixtures";
import {
  FIXED_TIME,
  type Scenario,
  type ScenarioState,
} from "../harness/scenario-state";
import { agentNode } from "../harness/sync-fixtures";

const SETTINGS_ROUTE = `/agent/${AGENT}/settings`;

// Small DTOs duplicated on this side of the seam. The src api types live in the
// app tsconfig project.
interface Usage {
  meters: {
    label: string;
    used_pct: number | null;
    resets_at: string | null;
  }[];
  credits: { used: number | null; limit: number | null } | null;
  account: {
    name: string | null;
    email: string | null;
    plan: string | null;
    organization: string | null;
    created_at: string | null;
  } | null;
}

interface BackupInfo {
  id: string;
  agent_name: string;
  backup_type: string;
  created_at: string;
  size: number;
  from_version?: string | null;
  vestad_version?: string | null;
}

interface FieldPredicate {
  field: string;
  op: "contains" | "regex";
  value: string;
  negate?: boolean;
}

interface NotificationInterruptRule {
  id: string;
  source?: string | null;
  type?: string | null;
  match?: FieldPredicate[];
  action: "interrupt" | "snooze" | "trash";
}

interface HostMount {
  host_path: string;
  container_path: string;
  writable: boolean;
}

interface FileTreeEntry {
  path: string;
  is_dir: boolean;
  mode: number;
}

interface VoiceSetting {
  key: string;
  type: "bool" | "number" | "select";
  label: string;
  description?: string;
  value: unknown;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string; description?: string }[];
}

interface VoiceStatus {
  configured: boolean;
  provider: string | null;
  enabled?: boolean;
  settings?: VoiceSetting[];
}

const MB = 1024 * 1024;

function agentRoute(
  path: string,
  json: unknown,
  extra: Partial<RouteFixture> = {},
): RouteFixture {
  return { path: `/agents/${AGENT}${path}`, json, ...extra };
}

function failure(path: string, error: string, status = 500): RouteFixture {
  return agentRoute(path, { error }, { status });
}

function hang(path: string): RouteFixture {
  return agentRoute(path, undefined, { hang: true });
}

function isoFromNow(minutes: number): string {
  return new Date(FIXED_TIME.getTime() + minutes * 60_000).toISOString();
}

// The Claude context policy the real provider catalog ships (three presets, two of
// them Max-only), so the context dialog shows a full preset list.
const CLAUDE_CONTEXT = {
  default: 1_000_000,
  max: 1_000_000,
  defaults_by_plan: { max: 1_000_000, pro: 200_000, free: 200_000 },
  presets: [
    { tokens: 1_000_000, label: "1M", note: "most context", plans: ["max"] },
    { tokens: 500_000, label: "500K", note: "balanced", plans: ["max"] },
    {
      tokens: 200_000,
      label: "200K",
      note: "cheapest prompt-cache reads, compacts soonest",
    },
  ],
};

const CLAUDE_CATALOG_ENTRY = PROVIDER_CATALOG.providers.claude;
if (CLAUDE_CATALOG_ENTRY === undefined) {
  throw new Error("the visual provider fixture must include Claude");
}

const SETTINGS_PROVIDER_CATALOG: ProviderCatalog = {
  ...PROVIDER_CATALOG,
  providers: {
    ...PROVIDER_CATALOG.providers,
    claude: { ...CLAUDE_CATALOG_ENTRY, context: CLAUDE_CONTEXT },
  },
};

const CLAUDE_PROVIDER: ProviderInfoFixture = {
  kind: "claude",
  model: "opus-latest",
  resolved_model: "claude-opus-5",
  max_context_tokens: 1_000_000,
  authed: true,
  plan: "max",
};

const OPENROUTER_PROVIDER: ProviderInfoFixture = {
  kind: "openrouter",
  model: "anthropic/claude-sonnet-5",
  resolved_model: "anthropic/claude-sonnet-5",
  max_context_tokens: null,
  authed: true,
  plan: null,
};

const CLAUDE_USAGE: Usage = {
  meters: [
    { label: "current session", used_pct: 42, resets_at: isoFromNow(137) },
    {
      label: "current week",
      used_pct: 18,
      resets_at: isoFromNow(3 * 24 * 60 + 260),
    },
    {
      label: "current week (opus)",
      used_pct: 7,
      resets_at: isoFromNow(3 * 24 * 60 + 260),
    },
  ],
  credits: null,
  account: {
    name: "Emilio",
    email: "emilio@example.com",
    plan: "max",
    organization: null,
    created_at: "2024-03-14T10:00:00Z",
  },
};

const OPENROUTER_USAGE: Usage = {
  meters: [],
  credits: { used: 12.34, limit: 50 },
  account: null,
};

const BACKUP_SETTINGS = {
  enabled: true,
  retention: { periodic: 1, pre_update_versions: 5 },
  has_override: false,
};

const BACKUPS: BackupInfo[] = [
  {
    id: "a1f3c9",
    agent_name: AGENT,
    backup_type: "periodic",
    created_at: "20260818-040001",
    size: 812 * MB,
    vestad_version: "0.2.3",
  },
  {
    id: "b7e210",
    agent_name: AGENT,
    backup_type: "manual",
    created_at: "20260816-183422",
    size: 809 * MB,
    vestad_version: "0.2.3",
  },
  {
    id: "c04d8e",
    agent_name: AGENT,
    backup_type: "pre_update",
    created_at: "20260812-040455",
    size: 774 * MB,
    from_version: "v0.2.2",
    vestad_version: "0.2.2",
  },
  {
    id: "d92b17",
    agent_name: AGENT,
    backup_type: "pre_restore",
    created_at: "20260803-091210",
    size: 751 * MB,
    vestad_version: "0.2.1",
  },
];

const STT_STATUS: VoiceStatus = {
  configured: true,
  provider: "deepgram",
  enabled: true,
  settings: [
    {
      key: "eot_threshold",
      type: "number",
      label: "end-of-turn sensitivity",
      description:
        "lower finalizes turns faster; higher waits for more confidence before ending the turn",
      value: 0.8,
      default: 0.8,
      min: 0.5,
      max: 0.9,
      step: 0.05,
    },
    {
      key: "interrupt_tts",
      type: "bool",
      label: "interrupt speech on talk",
      description: "stop text-to-speech playback when you start speaking",
      value: true,
      default: true,
    },
  ],
};

const TTS_STATUS: VoiceStatus = {
  configured: true,
  provider: "elevenlabs",
  enabled: true,
  settings: [
    {
      key: "selected_voice_id",
      type: "select",
      label: "voice",
      description: "select a voice for speech synthesis",
      value: "rachel",
      default: "rachel",
      options: [
        { value: "rachel", label: "Rachel", description: "calm" },
        { value: "adam", label: "Adam", description: "deep" },
        { value: "bella", label: "Bella", description: "soft" },
      ],
    },
  ],
};

const UNCONFIGURED_VOICE: VoiceStatus = { configured: false, provider: null };

const UNCONFIGURED_VOICE_ROUTES: RouteFixture[] = [
  agentRoute("/voice/stt/status", UNCONFIGURED_VOICE),
  agentRoute("/voice/tts/status", UNCONFIGURED_VOICE),
];

const STT_USAGE = {
  usage: { results: [{ hours: 0.75 }, { hours: 0.5 }] },
  balance: { balances: [{ amount: 12.5, units: "usd" }] },
};

const TTS_USAGE = {
  usage: { character_count: 12450, character_limit: 100000 },
};

let nextNotificationId = 500;

function notification(
  minutesAgo: number,
  fields: Omit<NotificationEvent, "id" | "ts" | "type">,
): NotificationEvent {
  return {
    id: nextNotificationId++,
    type: "notification",
    ts: isoFromNow(-minutesAgo),
    ...fields,
  };
}

const PENDING_NOTIFICATION = notification(6, {
  source: "whatsapp",
  notif_type: "message",
  sender: "Ana",
  notif_id: "whatsapp-2261",
  decided: "interrupt",
  summary:
    '<channel source="whatsapp" type="message" chat_name="Ana">did the PO number go out? finance is asking again</channel>',
});

// The history endpoint returns a page in ascending order; the card reverses it.
const NOTIFICATIONS: NotificationEvent[] = [
  notification(4 * 24 * 60 + 30, {
    source: "twitter",
    notif_type: "mention",
    sender: "@growthhackr",
    notif_id: "twitter-9910",
    decided: "trash",
    summary:
      '<channel source="twitter" type="mention">@luna_agent great thread, want to collab? DM me</channel>',
  }),
  notification(2 * 24 * 60 + 15, {
    source: "finance",
    notif_type: "transaction",
    sender: "Revolut",
    notif_id: "finance-3381",
    decided: "snooze",
    summary:
      '<channel source="finance" type="transaction" account="Revolut">card payment of 42.90 EUR at Trattoria da Enzo</channel>',
  }),
  notification(24 * 60 + 5, {
    source: "calendar",
    notif_type: "event",
    notif_id: "calendar-7742",
    decided: "interrupt",
    summary:
      '<channel source="calendar" type="event" title="Design review" start_time="3:00 PM" minutes_until="15" location="Room 4B">moved from 2pm, Marco added the new mocks</channel>',
  }),
  notification(3 * 60 + 12, {
    source: "email",
    notif_type: "message",
    sender: "invoices@acme.co",
    notif_id: "email-5120",
    decided: "snooze",
    summary:
      '<channel source="email" type="message" subject="Invoice #2261 due Friday" preview="Hi Emilio, a reminder that invoice #2261 is due this Friday. Let us know if you need the PO number." account="work" folder="inbox">Hi Emilio, a reminder that invoice #2261 is due this Friday. Let us know if you need the PO number.</channel>',
  }),
  PENDING_NOTIFICATION,
];

const RULES: NotificationInterruptRule[] = [
  { id: "rule-twitter", source: "twitter", action: "trash" },
  {
    id: "rule-bride-squad",
    source: "whatsapp",
    match: [{ field: "sender", op: "contains", value: "Bride Squad" }],
    action: "snooze",
  },
  {
    id: "rule-urgent-mail",
    source: "email",
    match: [{ field: "text", op: "regex", value: "urgent|asap" }],
    action: "interrupt",
  },
  {
    id: "rule-calendar",
    source: "calendar",
    type: "event",
    action: "interrupt",
  },
];

const MOUNTS: HostMount[] = [
  {
    host_path: "/Users/emilio/Documents",
    container_path: "/Users/emilio/Documents",
    writable: false,
  },
  { host_path: "/mnt/media", container_path: "/media", writable: true },
];

const HOST_FOLDERS = [
  "/Users/emilio/Downloads",
  "/Users/emilio/Projects",
  "/mnt/media",
];

const MEMORY_PATH = "/root/agent/MEMORY.md";

function dir(path: string): FileTreeEntry {
  return { path, is_dir: true, mode: 0o755 };
}
function file(path: string): FileTreeEntry {
  return { path, is_dir: false, mode: 0o644 };
}

const TREE: FileTreeEntry[] = [
  dir("/root/agent"),
  file(MEMORY_PATH),
  file("/root/agent/constitution.md"),
  dir("/root/agent/data"),
  file("/root/agent/data/config.json"),
  dir("/root/agent/dreamer"),
  file("/root/agent/dreamer/2026-08-16T0400.md"),
  file("/root/agent/dreamer/2026-08-17T0400.md"),
  dir("/root/agent/skills"),
  dir("/root/agent/skills/email"),
  file("/root/agent/skills/email/SKILL.md"),
  dir("/root/agent/skills/tasks"),
  file("/root/agent/skills/tasks/SKILL.md"),
  file("/root/agent/skills/tasks/REFERENCE.md"),
  dir("/root/agent/skills/whatsapp"),
  file("/root/agent/skills/whatsapp/SKILL.md"),
];

const MEMORY_FILE = {
  path: MEMORY_PATH,
  content: [
    "# Memory",
    "",
    "## Emilio",
    "- prefers short replies, no emoji",
    "- standup at 9:30, design review moved to 3pm on Thursdays",
    "- dentist: Dr. Bianchi, call before 5",
    "",
    "## Work",
    "- Ana (finance) needs PO numbers from the finance sheet",
    "- invoice #2261 sent as PO-2261 on Aug 16",
    "",
    "## Home",
    "- water the balcony plants on Tuesdays",
  ].join("\n"),
  encoding: "utf-8",
  readonly: false,
  mode: 0o644,
  size: 412,
  is_dir: false,
};

// Every gateway answer the settings page reads for an alive, fully set-up
// agent: a Claude Max provider with usage, automatic backups on with a
// snapshot history, both voice domains configured, notification history and
// rules, host folders, and the file tree. A scenario overrides what it shows.
const HAPPY_ROUTES: RouteFixture[] = [
  providerRoute(CLAUDE_PROVIDER, SETTINGS_PROVIDER_CATALOG),
  agentRoute("/usage", CLAUDE_USAGE),
  agentRoute("/provider/models", CLAUDE_MODELS),
  agentRoute("/settings/backup", BACKUP_SETTINGS),
  agentRoute("/backups", BACKUPS, { method: "GET" }),
  agentRoute("/voice/stt/status", STT_STATUS),
  agentRoute("/voice/tts/status", TTS_STATUS),
  agentRoute("/voice/stt/usage", STT_USAGE),
  agentRoute("/voice/tts/usage", TTS_USAGE),
  agentRoute(
    "/history",
    { events: NOTIFICATIONS, cursor: 41 },
    { query: { channel: "notifications" } },
  ),
  agentRoute("/config", { notification_rules: RULES }, { method: "GET" }),
  agentRoute("/mounts", { mounts: MOUNTS }, { method: "GET" }),
  { path: "/host/folders", json: { folders: HOST_FOLDERS } },
  agentRoute("/tree", { entries: TREE }),
  agentRoute("/file", MEMORY_FILE, { query: { path: MEMORY_PATH } }),
  ...chatRoutes(AGENT),
];

// The voice service is what makes the settings page read the voice status.
function settingsAgent(
  status: Parameters<typeof agentNode>[0] = "alive",
): AgentNode {
  return agentNode(status, {
    services: { voice: { port: 8765, rev: 1, public: false } },
  });
}

function settingsState(
  overrides: {
    agent?: AgentNode;
    routes?: RouteFixture[];
    storage?: Record<string, string>;
  } = {},
): ScenarioState {
  return {
    route: SETTINGS_ROUTE,
    sync: { agents: { [AGENT]: overrides.agent ?? settingsAgent() } },
    routes: [...HAPPY_ROUTES, ...(overrides.routes ?? [])],
    storage: overrides.storage,
    chatSocket: { agent: AGENT, events: [] },
  };
}

const noDrive = (): Promise<void> => Promise.resolve();

function card(page: Page, text: string) {
  return page.locator('[data-slot="card"]', { hasText: text });
}

async function openTab(page: Page, name: string): Promise<void> {
  await page.getByRole("tab", { name }).click();
}
async function openModelDialog(page: Page): Promise<void> {
  await page.getByRole("button", { name: "change model" }).click();
}
async function openBackupsDialog(page: Page): Promise<void> {
  await page.getByRole("button", { name: "backup", exact: true }).click();
}
async function scrollToVoice(page: Page): Promise<void> {
  await page.getByText("speech to text").scrollIntoViewIfNeeded();
}

function generalScenario(
  overrides: Parameters<typeof settingsState>[0],
  settle: (page: Page) => Promise<void>,
): Scenario {
  return { state: settingsState(overrides), drive: noDrive, settle };
}

// The general tab stacks its cards on a narrow screen, so a card-focused
// scenario brings its card into the viewport first. The provider card is the
// second card on every layout; it is scrolled once it has settled, since the
// loading card is swapped out for the loaded one.
function providerScenario(
  overrides: Parameters<typeof settingsState>[0],
  settle: (page: Page) => Promise<void>,
): Scenario {
  return {
    state: settingsState(overrides),
    drive: async (page) => {
      await settle(page);
      await page.locator('[data-slot="card"]').nth(1).scrollIntoViewIfNeeded();
    },
    settle,
  };
}

function backupsCardScenario(
  routes: RouteFixture[],
  settle: (page: Page) => Promise<void>,
): Scenario {
  return {
    state: settingsState({ routes }),
    drive: (page) => card(page, "automatic backups").scrollIntoViewIfNeeded(),
    settle,
  };
}

function backupsDialog(routes: RouteFixture[], visibleText: string): Scenario {
  return {
    state: settingsState({ routes }),
    drive: openBackupsDialog,
    settle: async (page) => {
      await expect(page.getByText(`backups for ${AGENT}`)).toBeVisible();
      await expect(page.getByText(visibleText)).toBeVisible();
    },
  };
}

function notificationsTab(
  routes: RouteFixture[],
  settle: (page: Page) => Promise<void>,
): Scenario {
  return {
    state: settingsState({ routes }),
    drive: (page) => openTab(page, "notifications"),
    settle,
  };
}

function filesTab(
  overrides: Parameters<typeof settingsState>[0],
  settle: (page: Page) => Promise<void>,
): Scenario {
  return {
    state: settingsState(overrides),
    drive: (page) => openTab(page, "files"),
    settle,
  };
}

export const AGENT_SETTINGS: Record<string, Scenario> = {
  "settings-general": generalScenario({}, async (page) => {
    await expect(page.getByText("current session")).toBeVisible();
    await expect(page.getByText("automatic backups")).toBeVisible();
    await expect(page.getByText("speech to text")).toBeVisible();
    await expect(page.getByText("text to speech")).toBeVisible();
  }),
  "settings-provider-loading": providerScenario(
    { routes: [hang("/provider")] },
    async (page) => {
      await expect(page.getByText("automatic backups")).toBeVisible();
      await expect(page.getByText("plan usage")).toBeHidden();
      await expect(
        page.locator('[data-slot="skeleton"]').first(),
      ).toBeVisible();
    },
  ),
  "settings-provider-none": providerScenario(
    {
      agent: settingsAgent("unprovisioned"),
      routes: [
        agentRoute("/provider", {
          model: null,
          authed: false,
          catalog: SETTINGS_PROVIDER_CATALOG,
        }),
        ...UNCONFIGURED_VOICE_ROUTES,
      ],
    },
    async (page) => {
      await expect(page.getByText("not connected")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "set up provider" }),
      ).toBeVisible();
    },
  ),
  "settings-provider-signed-out": providerScenario(
    {
      agent: settingsAgent("not_authenticated"),
      routes: [providerRoute({ ...CLAUDE_PROVIDER, authed: false })],
    },
    async (page) => {
      await expect(page.getByText("signed out")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "sign in again" }),
      ).toBeVisible();
    },
  ),
  "settings-provider-claude": providerScenario({}, async (page) => {
    await expect(page.getByText("current session")).toBeVisible();
    await expect(page.getByText("current week (opus)")).toBeVisible();
    await expect(page.getByText("emilio@example.com")).toBeVisible();
  }),
  "settings-provider-openrouter": providerScenario(
    {
      routes: [
        providerRoute(OPENROUTER_PROVIDER),
        agentRoute("/usage", OPENROUTER_USAGE),
      ],
    },
    async (page) => {
      await expect(page.getByText("$12.34 / $50.00")).toBeVisible();
      await expect(page.getByText("model context")).toBeVisible();
    },
  ),
  "settings-usage-loading": providerScenario(
    { routes: [hang("/usage")] },
    async (page) => {
      await expect(page.getByText("plan usage")).toBeVisible();
      await expect(page.getByText("current session")).toBeHidden();
      await expect(
        card(page, "plan usage").locator('[data-slot="skeleton"]').first(),
      ).toBeVisible();
    },
  ),
  "settings-usage-error": providerScenario(
    { routes: [failure("/usage", "usage endpoint unavailable")] },
    async (page) => {
      await expect(page.getByText("failed to load usage data")).toBeVisible();
    },
  ),
  "settings-model-claude": {
    state: settingsState(),
    drive: async (page) => {
      await openModelDialog(page);
      await page.getByRole("button", { name: "more models" }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("dialog")).toBeVisible();
      await expect(page.getByText("Claude Opus 5")).toBeVisible();
      await expect(page.getByText("Claude Haiku 4.5")).toBeVisible();
    },
  },
  "settings-model-openrouter": {
    state: settingsState({
      routes: [
        providerRoute(OPENROUTER_PROVIDER),
        agentRoute("/usage", OPENROUTER_USAGE),
      ],
    }),
    drive: openModelDialog,
    settle: async (page) => {
      await expect(page.getByPlaceholder("search models...")).toBeVisible();
      await expect(page.getByText("Kimi K2")).toBeVisible();
    },
  },
  "settings-model-error": {
    state: settingsState({
      routes: [
        agentRoute(
          "/provider",
          { error: "provider is locked while a restart is in flight" },
          { method: "PATCH", status: 500 },
        ),
      ],
    }),
    drive: async (page) => {
      await openModelDialog(page);
      await page.getByRole("button", { name: "Sonnet", exact: true }).click();
      await page.getByRole("button", { name: "switch model" }).click();
    },
    settle: async (page) => {
      await expect(
        page.getByText("provider is locked while a restart is in flight"),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "switch model" }),
      ).toBeVisible();
    },
  },
  "settings-context-dialog": {
    state: settingsState(),
    drive: async (page) => {
      await page.getByRole("button", { name: "change context" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("change context window")).toBeVisible();
      await expect(page.getByText("1M", { exact: true })).toBeVisible();
      await expect(page.getByText("500K", { exact: true })).toBeVisible();
      await expect(page.getByText("200K", { exact: true })).toBeVisible();
    },
  },
  "settings-sign-out-dialog": {
    state: settingsState(),
    drive: async (page) => {
      await page.getByRole("button", { name: "more actions" }).click();
      await page.getByRole("menuitem", { name: "sign out" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText(`sign out ${AGENT}?`)).toBeVisible();
      await expect(
        page.getByRole("button", { name: "sign out", exact: true }),
      ).toBeVisible();
    },
  },
  "settings-actions-stopped": generalScenario(
    {
      // A stopped container serves no services, so voice reads as unconfigured.
      agent: agentNode("stopped"),
      routes: [
        failure("/provider", "agent is not running", 503),
        failure("/usage", "agent is not running", 503),
      ],
    },
    async (page) => {
      await expect(
        page.getByRole("button", { name: "start", exact: true }),
      ).toBeVisible();
      await expect(
        page.getByRole("button", { name: "stop", exact: true }),
      ).toBeHidden();
    },
  ),
  "settings-actions-needs-auth": generalScenario(
    {
      agent: settingsAgent("not_authenticated"),
      routes: [providerRoute({ ...CLAUDE_PROVIDER, authed: false })],
    },
    async (page) => {
      await expect(
        page.getByRole("button", { name: "sign in", exact: true }),
      ).toBeVisible();
    },
  ),
  "settings-backups-loading": backupsCardScenario(
    [hang("/settings/backup")],
    async (page) => {
      const backups = card(page, "automatic backups");
      await expect(backups).toBeVisible();
      await expect(backups.getByRole("switch")).toBeHidden();
      await expect(backups.locator('[data-slot="skeleton"]')).toBeVisible();
    },
  ),
  "settings-backups-off": backupsCardScenario(
    [
      agentRoute("/settings/backup", {
        ...BACKUP_SETTINGS,
        enabled: false,
        has_override: true,
      }),
    ],
    async (page) => {
      await expect(
        card(page, "automatic backups").getByRole("switch"),
      ).toHaveAttribute("data-state", "unchecked");
    },
  ),
  "settings-backups-dialog": backupsDialog([], "Before update v0.2.2"),
  "settings-backups-dialog-empty": backupsDialog(
    [agentRoute("/backups", [], { method: "GET" })],
    "no snapshots yet.",
  ),
  "settings-backups-dialog-error": backupsDialog(
    [failure("/backups", "restic repository is locked")],
    "couldn't load snapshots.",
  ),
  "settings-voice-unconfigured": {
    state: settingsState({ routes: UNCONFIGURED_VOICE_ROUTES }),
    drive: scrollToVoice,
    settle: async (page) => {
      const warnings = page.getByText(
        "not configured — ask the agent to set it up",
      );
      await expect(warnings).toHaveCount(2);
      await expect(warnings.first()).toBeVisible();
    },
  },
  "settings-voice-enabled": {
    state: settingsState(),
    drive: async (page) => {
      await scrollToVoice(page);
      const usage = page.getByRole("button", { name: "usage", exact: true });
      await usage.nth(0).click();
      await usage.nth(1).click();
      await page
        .getByRole("button", { name: /^voice:/ })
        .scrollIntoViewIfNeeded();
    },
    settle: async (page) => {
      await expect(page.getByText("1.25 h used · $12.50 left")).toBeVisible();
      await expect(page.getByText("12,450 / 100,000")).toBeVisible();
    },
  },
  "settings-notifications-loading": notificationsTab(
    [hang("/history")],
    async (page) => {
      const history = card(page, "recent notifications");
      await expect(history).toBeVisible();
      await expect(
        history.locator('[data-slot="skeleton"]').first(),
      ).toBeVisible();
      await expect(page.getByText("add a rule")).toBeVisible();
    },
  ),
  "settings-notifications-empty": notificationsTab(
    [
      agentRoute(
        "/history",
        { events: [], cursor: null },
        { query: { channel: "notifications" } },
      ),
    ],
    async (page) => {
      await expect(page.getByText("No notifications yet")).toBeVisible();
    },
  ),
  "settings-notifications-error": notificationsTab(
    [failure("/history", "events database is locked")],
    async (page) => {
      await expect(
        page.getByText("failed to load: events database is locked"),
      ).toBeVisible();
    },
  ),
  "settings-notifications-list": {
    state: settingsState({
      agent: {
        ...settingsAgent(),
        notifications: { pending: [PENDING_NOTIFICATION] },
      },
    }),
    drive: (page) => openTab(page, "notifications"),
    settle: async (page) => {
      await expect(page.getByText("Invoice #2261 due Friday")).toBeVisible();
      await expect(page.getByText("Design review")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "load older" }),
      ).toBeVisible();
    },
  },
  "settings-rules-empty": notificationsTab(
    [agentRoute("/config", { notification_rules: [] }, { method: "GET" })],
    async (page) => {
      await expect(page.getByText("no rules yet")).toBeVisible();
    },
  ),
  "settings-rules-list": notificationsTab([], async (page) => {
    await expect(page.getByText("source: twitter")).toBeVisible();
    await expect(page.getByText("sender: Bride Squad")).toBeVisible();
    await expect(page.getByText("keyword: urgent|asap")).toBeVisible();
    await expect(page.getByText("add a rule")).toBeVisible();
  }),
  "settings-rules-error": notificationsTab(
    [failure("/config", "config store unreadable")],
    async (page) => {
      await expect(
        page.getByText("failed to load: config store unreadable"),
      ).toBeVisible();
    },
  ),
  "settings-host-access-empty": filesTab(
    { routes: [agentRoute("/mounts", { mounts: [] }, { method: "GET" })] },
    async (page) => {
      await expect(page.getByText("shared folders")).toBeVisible();
      await expect(page.getByText("add a folder")).toBeVisible();
      await expect(page.getByText("view only")).toBeHidden();
    },
  ),
  "settings-host-access-list": filesTab({}, async (page) => {
    await expect(page.getByText("Documents", { exact: true })).toBeVisible();
    await expect(page.getByText("view only")).toBeVisible();
    await expect(page.getByText("can edit")).toBeVisible();
    await expect(page.getByText("/mnt/media · seen at /media")).toBeVisible();
  }),
  "settings-host-access-add": {
    state: settingsState(),
    drive: async (page) => {
      await openTab(page, "files");
      await page.getByRole("button", { name: "add a folder" }).click();
    },
    settle: async (page) => {
      await expect(page.getByText("suggested folders")).toBeVisible();
      await expect(page.getByText("/Users/emilio/Downloads")).toBeVisible();
      await expect(
        page.getByRole("button", { name: "add folder" }),
      ).toBeDisabled();
    },
  },
  "settings-files-simple": filesTab({}, async (page) => {
    await expect(page.getByText(`who ${AGENT} is`)).toBeVisible();
    await expect(page.getByText("abilities")).toBeVisible();
    await expect(page.getByText("tasks", { exact: true })).toBeVisible();
    await expect(page.getByText("memory", { exact: true })).toBeVisible();
  }),
  "settings-files-editor": {
    state: settingsState(),
    drive: async (page) => {
      await openTab(page, "files");
      await page.getByText("memory", { exact: true }).click();
    },
    settle: async (page) => {
      await expect(page.getByRole("textbox")).toHaveValue(/# Memory/);
      await expect(page.getByRole("button", { name: "save" })).toBeDisabled();
    },
  },
  "settings-files-error": filesTab(
    { routes: [failure("/tree", "agent filesystem unavailable")] },
    async (page) => {
      await expect(
        page.getByText("failed to load: agent filesystem unavailable"),
      ).toBeVisible();
    },
  ),
};
