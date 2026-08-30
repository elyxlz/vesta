import type { Page } from "@playwright/test";
import type { VestaEvent } from "@vesta/core";
import type { RouteFixture } from "./http-fixtures";

// The app-chat service as the web client reads it: a minted service key, the
// newest history page, and the live socket. Chat state comes from history; the
// socket only streams what the fixture pushes after it opens.
export const SERVICE_KEY = {
  id: "visual-key",
  key: "visual-service-key",
  expires_at: null,
};

export interface ChatHistoryFixture {
  events?: VestaEvent[];
  cursor?: number | null;
  hang?: boolean;
}

export function chatRoutes(
  agent: string,
  history: ChatHistoryFixture = {},
): RouteFixture[] {
  return [
    {
      path: `/agents/${agent}/services/app-chat/keys`,
      method: "POST",
      json: SERVICE_KEY,
    },
    {
      path: `/agents/${agent}/app-chat/history`,
      json: { events: history.events ?? [], cursor: history.cursor ?? null },
      hang: history.hang,
    },
  ];
}

export async function installChatSocket(
  page: Page,
  agent: string,
  events: VestaEvent[],
): Promise<void> {
  const pattern = new RegExp(`/agents/${agent}/app-chat/ws`);
  await page.routeWebSocket(pattern, (ws) => {
    ws.onMessage(() => undefined);
    for (const event of events) ws.send(JSON.stringify(event));
  });
}

let nextEventId = 1000;

// Chat rows with ascending ids and stable timestamps: `at` is minutes before
// the fixed clock (harness/scenario-state.ts), so day stamps and relative
// labels never move between scans.
export function userMessage(text: string, minutesAgo: number): VestaEvent {
  return { id: nextEventId++, type: "user", text, ts: stamp(minutesAgo) };
}

export function agentMessage(text: string, minutesAgo: number): VestaEvent {
  return { id: nextEventId++, type: "chat", text, ts: stamp(minutesAgo) };
}

export function errorLine(text: string, minutesAgo: number): VestaEvent {
  return { id: nextEventId++, type: "error", text, ts: stamp(minutesAgo) };
}

export function rateLimitedLine(
  minutesAgo: number,
  resetsAt: number,
): VestaEvent {
  return {
    id: nextEventId++,
    type: "rate_limited",
    text: "rate limited",
    window: "5h",
    resets_at: resetsAt,
    ts: stamp(minutesAgo),
  };
}

const FIXED_NOW_MS = Date.parse("2026-08-18T10:00:00Z");

function stamp(minutesAgo: number): string {
  return new Date(FIXED_NOW_MS - minutesAgo * 60_000).toISOString();
}

export const CONVERSATION: VestaEvent[] = [
  userMessage(
    "morning! anything I should know before standup?",
    2 * 24 * 60 + 15,
  ),
  agentMessage(
    "morning. two things: the design review moved to 3pm, and Ana replied about the invoice, she needs the PO number by tomorrow.",
    2 * 24 * 60 + 14,
  ),
  userMessage(
    "can you send her the PO number from the finance sheet?",
    2 * 24 * 60 + 12,
  ),
  agentMessage("done, sent PO-2261 to Ana and cc'd you.", 2 * 24 * 60 + 11),
  userMessage("remind me to call the dentist at 4", 45),
  agentMessage("set. I'll nudge you at 3:55.", 44),
  userMessage(
    "> remind me to call the dentist at 4\n\nactually make it 4:30",
    6,
  ),
  agentMessage("moved to 4:30.", 5),
];

export const MARKDOWN_REPLY: VestaEvent[] = [
  userMessage("how do I rotate the api key again?", 12),
  agentMessage(
    [
      "## Rotating the key",
      "",
      "1. Open **Settings → Gateway**.",
      "2. Run the rotate command:",
      "",
      "```bash",
      "vestad rotate-key --confirm",
      "```",
      "",
      "| step | takes |",
      "| --- | --- |",
      "| rotate | 1s |",
      "| reconnect clients | ~10s |",
      "",
      "Every client will need the new [connect link](https://vesta.run/connect).",
    ].join("\n"),
    11,
  ),
];

// The chunked-upload contract as the composer drives it. One static id per scenario is enough:
// the chips render from client draft state, so a shot needs only the routes its files exercise.
export const ATTACHMENT_ID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

export interface AttachmentRoutesFixture {
  stallData?: boolean;
  failCreate?: boolean;
  // Routed fixtures still answer under Playwright's offline emulation, so the
  // parked-upload state needs the create to fail retryably instead.
  unreachableCreate?: boolean;
}

export function attachmentRoutes(
  agent: string,
  options: AttachmentRoutesFixture = {},
): RouteFixture[] {
  return [
    {
      path: `/agents/${agent}/app-chat/attachments`,
      method: "POST",
      ...(options.failCreate
        ? { status: 400, json: { error: "invalid mime type" } }
        : options.unreachableCreate
          ? { status: 503, json: { error: "proxy down" } }
          : { json: { id: ATTACHMENT_ID } }),
    },
    {
      path: `/agents/${agent}/app-chat/attachments/${ATTACHMENT_ID}/data`,
      method: "PUT",
      json: { ok: true, received: 4 },
      hang: options.stallData,
    },
    {
      path: `/agents/${agent}/app-chat/attachments/${ATTACHMENT_ID}/complete`,
      method: "POST",
      json: {
        attachment: {
          id: ATTACHMENT_ID,
          name: "notes.txt",
          mime: "text/plain",
          size: 4,
        },
      },
    },
  ];
}
