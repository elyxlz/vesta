import { createContext, use, useMemo, type ReactNode } from "react";
import * as Linking from "expo-linking";
import type { NotificationEvent } from "@vesta/core";
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

type SessionValue = ReturnType<typeof useProductionSession>;

const launchUrl = Linking.getLinkingURL();
const query = launchUrl === null ? {} : Linking.parse(launchUrl).queryParams;
const startsConnected = query?.visualSession === "connected";
export const visualConnection: ConnectionConfig = {
  url: "https://home.vesta.run",
  accessToken: "visual-access-token",
  refreshToken: "visual-refresh-token",
  expiresAt: Date.UTC(2030, 0, 1),
  hosted: true,
};
const notifications: NotificationEvent[] = [
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
  },
};
const usage: Usage = {
  meters: [
    { label: "Five-hour session", used_pct: 34, resets_at: null },
    { label: "Weekly allowance", used_pct: 61, resets_at: null },
  ],
  credits: null,
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

function createVisualApi(): ApiClient {
  const base = createApiClient({
    getConnection: () => visualConnection,
    onConnectionChange: async () => undefined,
    onSessionExpired: async () => undefined,
  });
  return {
    ...base,
    request: async () => new Response(null, { status: 204 }),
    json: async <ResponseBody,>(path: string): Promise<ResponseBody> => {
      if (path === "/manifest") return manifest as ResponseBody;
      // A started update keeps the sheet's spinner up, which is the state the
      // gateway-update-in-progress scenario captures.
      if (path === "/gateway/update") return { started: true } as ResponseBody;
      if (path.endsWith("/provider")) {
        return {
          kind: "claude",
          model: "claude-sonnet-4-5",
          max_context_tokens: 200_000,
          authed: true,
          plan: "Max",
        } as ResponseBody;
      }
      if (path.endsWith("/usage")) return usage as ResponseBody;
      if (path.endsWith("/config")) {
        return { notification_rules: notificationRules } as ResponseBody;
      }
      if (path.endsWith("/mounts")) {
        return { mounts, restart_required: false } as ResponseBody;
      }
      if (path === "/host/folders") {
        return {
          folders: [
            "/Users/ada/Desktop",
            "/Users/ada/Downloads",
            "/Users/ada/Projects",
          ],
        } as ResponseBody;
      }
      if (path.endsWith("/settings/backup")) {
        return {
          enabled: true,
          retention: { periodic: 2, pre_update_versions: 2 },
          has_override: false,
        } as ResponseBody;
      }
      if (path.endsWith("/backups")) return backups as ResponseBody;
      if (path.includes("/voice/stt/status")) {
        return voiceStatuses.stt as ResponseBody;
      }
      if (path.includes("/voice/tts/status")) {
        return voiceStatuses.tts as ResponseBody;
      }
      if (path.includes("/history?channel=notifications")) {
        return { events: notifications, cursor: null } as ResponseBody;
      }
      if (path.endsWith("/tree")) {
        return { tree: fileTree.map((entry) => entry.path), entries: fileTree } as ResponseBody;
      }
      if (path.includes("/file?")) return memoryFile as ResponseBody;
      throw new Error(`No visual API fixture is registered for ${path}`);
    },
    serviceKeys: {
      get: async () => "visual-dashboard-key",
      drop: () => undefined,
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
