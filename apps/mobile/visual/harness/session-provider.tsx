import { createContext, use, useMemo, type ReactNode } from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import type { NotificationEvent, ProviderInfoWire } from "@vesta/core";
import { createApiClient } from "../../src/api/client";
import type { ApiClient } from "../../src/api/client";
import type {
  BackupInfo,
  ConnectionConfig,
  FileReadResponse,
  FileTreeEntry,
  HostMount,
  Manifest,
  NotificationInterruptRule,
  Usage,
  VoiceStatus,
} from "../../src/api/types";
import {
  SessionProvider as ProductionSessionProvider,
  useSession as useProductionSession,
} from "../../src/session/SessionProvider";
import {
  WHATS_NEW_LAST_SEEN_KEY,
  visualDelay,
  visualSwitch,
} from "./launch-query";

type SessionValue = ReturnType<typeof useProductionSession>;

// Seeded at import, ahead of the auto-open effect's read: AsyncStorage runs
// its calls in order, so the marker is in place by the time it is checked.
const whatsNewSeen = visualSwitch("visualWhatsNewSeen");
if (whatsNewSeen !== null) {
  void AsyncStorage.setItem(WHATS_NEW_LAST_SEEN_KEY, whatsNewSeen);
}

const startsConnected = visualSwitch("visualSession") === "connected";
// visualProvider selects aria's provider state: the signed-in Claude default,
// `none` (no provider yet), `unauthenticated` (Claude, credentials gone),
// `openai`, or `openrouter` (a key provider with credits).
const providerVariant = visualSwitch("visualProvider");
const voiceUnconfigured = visualSwitch("visualVoice") === "unconfigured";
// visualApi=error makes every agent read fail, which is how each section's
// error state is captured; one launch per section.
const apiFails = visualSwitch("visualApi") === "error";
export const visualConnection: ConnectionConfig = {
  url: "https://home.vesta.run",
  accessToken: "visual-access-token",
  refreshToken: "visual-refresh-token",
  expiresAt: Date.UTC(2030, 0, 1),
  hosted: true,
};
export const notifications: NotificationEvent[] = [
  {
    id: 401,
    type: "notification",
    source: "calendar",
    notif_type: "calendar",
    notif_id: "calendar-design-review",
    sender: "Product team",
    summary:
      '<channel source="calendar" type="calendar" subject="Design review" location="Studio" minutes_until="15"></channel>',
    fields: {
      subject: "Design review",
      location: "Studio",
      minutes_until: "15",
    },
    decided: "interrupt",
    ts: "2026-08-01T09:30:00.000Z",
  },
  {
    id: 402,
    type: "notification",
    source: "email",
    notif_type: "email",
    notif_id: "email-mobile-qa",
    sender: "Maya Chen",
    summary:
      '<channel source="email" type="email" subject="Mobile QA ready" preview="The onboarding screenshots are ready for review." account="work@vesta.run"></channel>',
    fields: {
      subject: "Mobile QA ready",
      preview: "The onboarding screenshots are ready for review.",
      account: "work@vesta.run",
      folder: "Inbox",
    },
    decided: "snooze",
    ts: "2026-08-01T08:45:00.000Z",
  },
  {
    id: 403,
    type: "notification",
    source: "messages",
    notif_type: "message",
    notif_id: "message-launch-room",
    sender: "Launch room",
    summary:
      '<channel source="messages" type="message" chat_name="Launch room">The latest build looks much cleaner.</channel>',
    decided: "trash",
    ts: "2026-08-01T08:12:00.000Z",
  },
];
const fileTree: FileTreeEntry[] = [
  { path: "/root/agent/MEMORY.md", is_dir: false, mode: 0o644 },
  { path: "/root/agent/constitution.md", is_dir: false, mode: 0o644 },
  {
    path: "/root/agent/dreamer/2026-08-01T03:00.md",
    is_dir: false,
    mode: 0o644,
  },
  {
    path: "/root/agent/skills/calendar/SKILL.md",
    is_dir: false,
    mode: 0o644,
  },
  {
    path: "/root/agent/skills/calendar/references/events.md",
    is_dir: false,
    mode: 0o644,
  },
  {
    path: "/root/agent/skills/mobile-qa/SKILL.md",
    is_dir: false,
    mode: 0o644,
  },
];
const manifest: Manifest = {
  default_provider: "claude",
  default_personality: "thoughtful",
  personalities: [],
  providers: {
    claude: {
      display: "Claude",
      order: 1,
      auth_kind: "claude_oauth",
      models: ["claude-sonnet-4-5", "claude-opus-4-1"],
      model_names: {
        "claude-sonnet-4-5": "Claude Sonnet 4.5",
        "claude-opus-4-1": "Claude Opus 4.1",
      },
      default_model: "claude-sonnet-4-5",
      context: {
        default: 200_000,
        max: 200_000,
        presets: [
          { tokens: 100_000, label: "Standard", note: "Faster compaction" },
          { tokens: 200_000, label: "Extended", note: "More history" },
        ],
      },
    },
    openai: {
      display: "OpenAI",
      order: 2,
      auth_kind: "device_oauth",
      models: ["gpt-5.2"],
      model_names: { "gpt-5.2": "GPT-5.2" },
      default_model: "gpt-5.2",
      context: { default: 128_000, max: 128_000, presets: [] },
    },
    openrouter: {
      display: "OpenRouter",
      order: 3,
      auth_kind: "api_key",
      models: "live",
      default_model: null,
      context: { default: 200_000, max: 200_000, presets: [] },
    },
  },
};
const usage: Usage = {
  meters: [
    { label: "Five-hour session", used_pct: 34, resets_at: null },
    { label: "Weekly allowance", used_pct: 61, resets_at: null },
  ],
  credits: null,
  account: {
    name: "Ada Lovelace",
    email: "ada@example.com",
    plan: "Claude Max",
    organization: "Ada's Organization",
    created_at: "2023-07-18T19:44:58Z",
  },
};
const openRouterUsage: Usage = {
  meters: [],
  credits: { used: 12.4, limit: 50 },
  account: null,
};
const claudeProvider: ProviderInfoWire = {
  kind: "claude",
  model: "claude-sonnet-4-5",
  max_context_tokens: 200_000,
  authed: true,
  plan: "Max",
};
const providers: Record<string, ProviderInfoWire> = {
  none: { authed: false },
  unauthenticated: {
    kind: "claude",
    model: "claude-sonnet-4-5",
    max_context_tokens: 200_000,
    authed: false,
    plan: null,
  },
  openai: {
    kind: "openai",
    model: "gpt-5.2",
    max_context_tokens: 128_000,
    authed: true,
    plan: "Plus",
  },
  openrouter: {
    kind: "openrouter",
    model: "anthropic/claude-sonnet-4-5",
    max_context_tokens: 200_000,
    authed: true,
    plan: null,
  },
};
const provider: ProviderInfoWire =
  (providerVariant === null ? undefined : providers[providerVariant]) ??
  claudeProvider;
const oauthStart = {
  auth_url: "https://claude.ai/oauth/authorize?visual-fixture",
  session_id: "visual-oauth-session",
};
const openAIOAuthStart = {
  auth_url: "https://chatgpt.com/device?visual-fixture",
  user_code: "WDJB-MJHT",
  session_id: "visual-openai-session",
};
const unconfiguredVoice: VoiceStatus = {
  configured: false,
  provider: null,
  enabled: false,
  settings: [],
};
const notificationRules: NotificationInterruptRule[] = [
  {
    id: "visual-calendar",
    source: "calendar",
    type: "calendar",
    match: [{ field: "minutes_until", op: "contains", value: "15" }],
    action: "interrupt",
  },
  {
    id: "visual-email",
    source: "email",
    match: [{ field: "sender", op: "contains", value: "Maya" }],
    action: "snooze",
  },
];
const mounts: HostMount[] = [
  {
    host_path: "/Users/ada/Projects/vesta",
    container_path: "/workspace/vesta",
    writable: true,
  },
  {
    host_path: "/Users/ada/Documents/Briefs",
    container_path: "/references/briefs",
    writable: false,
  },
];
const backups: BackupInfo[] = [
  {
    id: "visual-backup-1",
    agent_name: "aria",
    backup_type: "manual",
    created_at: "20260801-084500",
    size: 18_874_368,
  },
  {
    id: "visual-backup-2",
    agent_name: "aria",
    backup_type: "automatic",
    created_at: "20260731-030000",
    size: 17_825_792,
  },
];
const voiceStatuses: Record<"stt" | "tts", VoiceStatus> = {
  stt: {
    configured: true,
    provider: "Deepgram Nova-3",
    enabled: true,
    settings: [
      {
        key: "language",
        type: "select",
        label: "Language",
        description: "Language used for live transcription.",
        value: "English",
        options: [
          { value: "English", label: "English" },
          { value: "Spanish", label: "Spanish" },
        ],
      },
      {
        key: "smart_format",
        type: "bool",
        label: "Smart formatting",
        description: "Format dates, numbers, and punctuation automatically.",
        value: true,
      },
    ],
  },
  tts: {
    configured: true,
    provider: "ElevenLabs",
    enabled: true,
    settings: [
      {
        key: "voice",
        type: "select",
        label: "Voice",
        description: "Voice used when replies are read aloud.",
        value: "Warm",
        options: [
          { value: "Warm", label: "Warm" },
          { value: "Clear", label: "Clear" },
        ],
      },
      {
        key: "stability",
        type: "number",
        label: "Stability",
        description: "Balance consistency and expression.",
        value: 0.65,
      },
    ],
  },
};
const memoryFile: FileReadResponse = {
  path: "/root/agent/MEMORY.md",
  content: `# Working memory

## Current priorities

- Polish the mobile onboarding experience.
- Keep visual QA deterministic and fast.
- Prepare the product review notes for Monday.

## Preferences

Ada prefers concise updates with decisions and blockers called out clearly.
`,
  encoding: "utf-8",
  readonly: false,
  mode: 0o644,
  size: 264,
  is_dir: false,
};
const FixtureContext = createContext<SessionValue | null>(null);

// nova is the agent with nothing yet: no notifications, rules, backups,
// mounts, or files, so opening nova's sections renders every empty state.
function isNova(path: string): boolean {
  return path.startsWith("/agents/nova/");
}

function fixtureFor(path: string): unknown {
  if (path === "/manifest") return manifest;
  // A started update keeps the sheet's spinner up, which is the state the
  // gateway-update-in-progress scenario captures.
  if (path === "/gateway/update") return { started: true };
  if (path === "/providers/claude/oauth/start") return oauthStart;
  if (path === "/providers/openai/oauth/start") return openAIOAuthStart;
  if (path === "/providers/claude/oauth/complete") {
    return { credentials: "visual-claude-credentials" };
  }
  if (path === "/providers/openai/oauth/complete") {
    return { credentials: "visual-openai-credentials" };
  }
  if (path.startsWith("/providers/openrouter/models/top")) {
    return [
      {
        slug: "anthropic/claude-sonnet-4-5",
        label: "Claude Sonnet 4.5",
        author: "Anthropic",
      },
      { slug: "openai/gpt-5.2", label: "GPT-5.2", author: "OpenAI" },
      { slug: "moonshotai/kimi-k2", label: "Kimi K2", author: "MoonshotAI" },
    ];
  }
  if (path === "/host/folders") {
    return {
      folders: [
        "/Users/ada/Desktop",
        "/Users/ada/Downloads",
        "/Users/ada/Projects",
      ],
    };
  }
  if (apiFails && path.startsWith("/agents/")) {
    throw new Error("The gateway did not answer.");
  }
  if (path.endsWith("/provider")) return provider;
  if (path.endsWith("/usage")) {
    if (!provider.authed) return { meters: [], credits: null, account: null };
    return provider.kind === "openrouter" ? openRouterUsage : usage;
  }
  if (path.endsWith("/config")) {
    return { notification_rules: isNova(path) ? [] : notificationRules };
  }
  if (path.endsWith("/mounts")) {
    return { mounts: isNova(path) ? [] : mounts, restart_required: false };
  }
  if (path.endsWith("/settings/backup")) {
    return {
      enabled: true,
      retention: { periodic: 2, pre_update_versions: 2 },
      has_override: false,
    };
  }
  if (path.endsWith("/backups")) return isNova(path) ? [] : backups;
  if (path.includes("/voice/stt/status")) {
    return voiceUnconfigured ? unconfiguredVoice : voiceStatuses.stt;
  }
  if (path.includes("/voice/tts/status")) {
    return voiceUnconfigured ? unconfiguredVoice : voiceStatuses.tts;
  }
  if (path.includes("/history?channel=notifications")) {
    return { events: isNova(path) ? [] : notifications, cursor: null };
  }
  if (path.endsWith("/tree")) {
    const entries = isNova(path) ? [] : fileTree;
    return { tree: entries.map((entry) => entry.path), entries };
  }
  if (path.includes("/file?")) return memoryFile;
  throw new Error(`No visual API fixture is registered for ${path}`);
}

function createVisualApi(): ApiClient {
  const base = createApiClient({
    getConnection: () => visualConnection,
    onConnectionChange: async () => undefined,
    onSessionExpired: async () => undefined,
  });
  return {
    ...base,
    request: async (path: string) => {
      await visualDelay();
      if (apiFails) throw new Error("The gateway did not answer.");
      // The attachment probes: a removed blob is a stable 410, the broken one a server error.
      if (path.includes("/attachments/att-removed"))
        return new Response(null, { status: 410 });
      if (path.includes("/attachments/att-broken"))
        return new Response(null, { status: 500 });
      return new Response(null, { status: 204 });
    },
    json: async <ResponseBody,>(path: string): Promise<ResponseBody> => {
      await visualDelay();
      return fixtureFor(path) as ResponseBody;
    },
    serviceKeys: {
      get: async () => "visual-dashboard-key",
    },
  };
}

function FixtureProvider({ children }: { children: ReactNode }) {
  const value = useMemo<SessionValue | null>(() => {
    if (!startsConnected) return null;
    const api = createVisualApi();
    return {
      status: "connected",
      connection: visualConnection,
      api,
      recentGateways: [],
      refreshAccessToken: async () => true,
      connectLink: async () => undefined,
      connectRecentGateway: async () => undefined,
      forgetRecentGateway: async () => undefined,
      clearRecentGateways: async () => undefined,
      signIn: async () => true,
      disconnect: async () => undefined,
    };
  }, []);

  return (
    <FixtureContext.Provider value={value}>{children}</FixtureContext.Provider>
  );
}

export function SessionProvider({ children }: { children: ReactNode }) {
  return (
    <ProductionSessionProvider>
      <FixtureProvider>{children}</FixtureProvider>
    </ProductionSessionProvider>
  );
}

export function useSession(): SessionValue {
  const fixture = use(FixtureContext);
  const production = useProductionSession();
  return fixture ?? production;
}
