import { createContext, use, useMemo, type ReactNode } from "react";
import * as Linking from "expo-linking";
import type { NotificationEvent } from "@vesta/core";
import { createApiClient } from "../../src/api/client";
import type { ApiClient } from "../../src/api/client";
import type { ConnectionConfig, FileTreeEntry } from "../../src/api/types";
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
      if (path.includes("/history?channel=notifications")) {
        return { events: notifications, cursor: null } as ResponseBody;
      }
      if (path.endsWith("/tree")) {
        return { tree: fileTree.map((entry) => entry.path), entries: fileTree } as ResponseBody;
      }
      throw new Error(`No visual API fixture is registered for ${path}`);
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
