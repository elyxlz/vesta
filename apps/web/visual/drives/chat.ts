import { expect, type Locator, type Page } from "@playwright/test";
import type { AgentStatus, VestaEvent } from "@vesta/core";
import {
  CONVERSATION,
  MARKDOWN_REPLY,
  agentMessage,
  attachmentRoutes,
  chatRoutes,
  errorLine,
  rateLimitedLine,
  userMessage,
  type ChatHistoryFixture,
} from "../harness/chat-fixtures";
import {
  AGENT,
  providerRoute,
  type ProviderInfoFixture,
  type RouteFixture,
} from "../harness/http-fixtures";
import type { Scenario, ScenarioState } from "../harness/scenario-state";
import { agentNode } from "../harness/sync-fixtures";

const CHAT_ROUTE = `/agent/${AGENT}/chat`;
const HISTORY_PATH = `/agents/${AGENT}/app-chat/history`;
const MESSAGE_PATH = `/agents/${AGENT}/app-chat/message`;
const LOGS_PATH = `/agents/${AGENT}/logs`;
const FIXED_NOW_SECS = Math.floor(Date.parse("2026-08-18T10:00:00Z") / 1000);
const TWO_HOURS_SECS = 2 * 60 * 60;

// The first assertion of a scenario also waits out the app's initial load and
// the chat history seed, so it gets a longer bound than the default 5s.
const LOADED = { timeout: 30_000 };

const CLAUDE_PROVIDER: ProviderInfoFixture = {
  kind: "claude",
  model: "opus-latest",
  resolved_model: "claude-opus-5",
  max_context_tokens: 131072,
  authed: true,
  plan: "max",
};

// The full-screen chat of a connectable agent, with history from the fixture
// and a live socket that streams nothing: every chat state is history-driven.
function chatState(
  history: ChatHistoryFixture,
  options: { status?: AgentStatus; routes?: RouteFixture[] } = {},
): ScenarioState {
  return {
    route: CHAT_ROUTE,
    sync: { agents: { [AGENT]: agentNode(options.status ?? "alive") } },
    routes: [...chatRoutes(AGENT, history), ...(options.routes ?? [])],
    chatSocket: { agent: AGENT, events: [] },
  };
}

function chatScenario(
  history: ChatHistoryFixture,
  settle: (page: Page) => Promise<void>,
  options: { status?: AgentStatus; routes?: RouteFixture[] } = {},
): Scenario {
  return {
    state: chatState(history, options),
    drive: () => Promise.resolve(),
    settle,
  };
}

// A status line lands after the conversation: the turn it reports on failed.
const RATE_LIMITED_HISTORY: VestaEvent[] = [
  ...CONVERSATION,
  userMessage("can you draft the reply to the landlord?", 3),
  rateLimitedLine(2, FIXED_NOW_SECS + TWO_HOURS_SECS),
];

const ERROR_HISTORY: VestaEvent[] = [
  ...CONVERSATION,
  userMessage("can you draft the reply to the landlord?", 3),
  errorLine("turn failed", 2),
];

// Thirty rows across a morning, oldest first, with more history behind them.
function longHistory(): VestaEvent[] {
  const events: VestaEvent[] = [];
  for (let step = 15; step >= 1; step--) {
    events.push(
      userMessage(`what's the status on item ${String(step)}?`, step * 20 + 5),
      agentMessage(
        `item ${String(step)} is on track, nothing needs you right now.`,
        step * 20 + 4,
      ),
    );
  }
  return events;
}

const LONG_HISTORY = longHistory();
const OLDEST_LONG_ID = LONG_HISTORY[0]?.id ?? 0;

const ESC = "\u001b";
const LOG_LINES = [
  `${ESC}[2m2026-08-18 09:58:01${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.main: agent luna starting, engine 0.2.3`,
  `${ESC}[2m2026-08-18 09:58:02${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.events: events.db at schema version 2`,
  `${ESC}[2m2026-08-18 09:58:02${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.claude_runtime: linked 5 vestad helpers onto PATH`,
  `${ESC}[2m2026-08-18 09:58:03${ESC}[0m ${ESC}[36mDEBUG${ESC}[0m core.config: provider=claude model=opus-latest context=131072`,
  `${ESC}[2m2026-08-18 09:58:04${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.api: listening on 0.0.0.0:8765`,
  `${ESC}[2m2026-08-18 09:58:05${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.loops: monitor_loop watching ~/agent/notifications`,
  `${ESC}[2m2026-08-18 09:58:09${ESC}[0m ${ESC}[33mWARNING${ESC}[0m core.upstream_sync: agent-v0.2.3 not in HEAD, queueing sync turn`,
  `${ESC}[2m2026-08-18 09:58:10${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.loops: boot turn 1/2 greeting`,
  `${ESC}[2m2026-08-18 09:59:41${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.loops: boot turn 2/2 upstream-sync`,
  `${ESC}[2m2026-08-18 09:59:58${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.loops: batch of 2 notifications source=app-chat`,
  `${ESC}[2m2026-08-18 09:59:59${ESC}[0m ${ESC}[31mERROR${ESC}[0m core.tools: user_devices: gateway answered 503, retrying`,
  `${ESC}[2m2026-08-18 10:00:00${ESC}[0m ${ESC}[32mINFO${ESC}[0m core.loops: turn complete in 3.2s, idle`,
];

const LOG_BODY = LOG_LINES.map((line) => `data: ${line}\n\n`).join("");

function logsRoute(fixture: Omit<RouteFixture, "path">): RouteFixture {
  return { path: LOGS_PATH, ...fixture };
}

const LOG_LINES_ROUTE = logsRoute({
  body: LOG_BODY,
  contentType: "text/event-stream",
});

function logsState(route: RouteFixture, page = "logs"): ScenarioState {
  return {
    route: `/agent/${AGENT}/${page}`,
    sync: { agents: { [AGENT]: agentNode("alive") } },
    routes: [route, providerRoute(CLAUDE_PROVIDER)],
  };
}

async function settleLogLines(page: Page): Promise<void> {
  await expect(logText(page, "agent luna starting")).toBeVisible(LOADED);
  await expect(logText(page, "— agent stopped —")).toBeVisible();
}

// The standalone logs pane stays mounted (hidden Activity) behind the settings
// logs tab, so log text is scoped to the visible console.
function logText(page: Page, text: string): Locator {
  return page.getByText(text).filter({ visible: true });
}

// The chat also mirrors the latest agent reply into an sr-only live region, and
// keeps a hidden height-measurement clone of the thread, so chat text is scoped
// to the visible copy.
function bubble(page: Page, text: string): Locator {
  return page.getByRole("paragraph").filter({ hasText: text });
}

function chatText(page: Page, text: string): Locator {
  return page.getByText(text).filter({ visible: true });
}

function composer(page: Page): Locator {
  return page.getByPlaceholder(`message ${AGENT}`).filter({ visible: true });
}

async function typeMessage(page: Page, text: string): Promise<void> {
  await composer(page).fill(text);
}

async function hoverMessageArea(page: Page): Promise<void> {
  const box = await composer(page).boundingBox();
  if (!box) throw new Error("chat composer not laid out");
  await page.mouse.move(box.x + box.width / 2, box.y - 250);
}

// Feed files straight into the composer's hidden picker input; the popover flow
// itself is covered by chat-attach-menu.
async function pickFiles(
  page: Page,
  files: { name: string; mimeType: string; buffer: Buffer }[],
): Promise<void> {
  await expect(composer(page)).toBeVisible(LOADED);
  await page
    .getByLabel("pick a file")
    .filter({ visible: false })
    .first()
    .setInputFiles(files);
}

const SMALL_FILE = {
  name: "notes.txt",
  mimeType: "text/plain",
  buffer: Buffer.from("abcd"),
};

export const CHAT: Record<string, Scenario> = {
  "chat-history-skeleton": chatScenario({ hang: true }, async (page) => {
    await expect(
      page.locator(".animate-pulse").filter({ visible: true }).first(),
    ).toBeVisible(LOADED);
    await expect(composer(page)).toBeVisible();
  }),
  "chat-empty": chatScenario({ events: [] }, async (page) => {
    await expect(chatText(page, `${AGENT} is setting things up`)).toBeVisible(
      LOADED,
    );
    await expect(composer(page)).toBeEnabled();
  }),
  "chat-needs-sign-in": chatScenario(
    { events: [] },
    async (page) => {
      await expect(chatText(page, `${AGENT} needs to sign in`)).toBeVisible(
        LOADED,
      );
      await expect(
        page.getByPlaceholder("sign in to chat").filter({ visible: true }),
      ).toBeDisabled();
    },
    { status: "not_authenticated" },
  ),
  "chat-populated": chatScenario({ events: CONVERSATION }, async (page) => {
    await expect(bubble(page, "moved to 4:30.")).toBeVisible(LOADED);
    await expect(chatText(page, "beginning of conversation")).toBeVisible();
  }),
  "chat-markdown": chatScenario({ events: MARKDOWN_REPLY }, async (page) => {
    await expect(
      page.getByRole("heading", { name: "Rotating the key" }),
    ).toBeVisible(LOADED);
    await expect(
      page.getByRole("link", { name: "connect link" }),
    ).toBeVisible();
    await expect(
      page.getByRole("cell", { name: "reconnect clients" }),
    ).toBeVisible();
  }),
  "chat-error-line": chatScenario({ events: ERROR_HISTORY }, async (page) => {
    await expect(
      chatText(page, "hit a snag, this may not have gone through"),
    ).toBeVisible(LOADED);
  }),
  "chat-rate-limited": chatScenario(
    { events: RATE_LIMITED_HISTORY },
    async (page) => {
      await expect(chatText(page, "rate limited, back in 2h")).toBeVisible(
        LOADED,
      );
    },
  ),
  "chat-send-failed": {
    state: chatState(
      { events: CONVERSATION },
      {
        routes: [
          {
            path: MESSAGE_PATH,
            method: "POST",
            status: 500,
            json: { error: "app-chat intake failed" },
          },
        ],
      },
    ),
    drive: async (page) => {
      await expect(bubble(page, "moved to 4:30.")).toBeVisible(LOADED);
      await typeMessage(page, "and book the table for friday at 8");
      await page.getByRole("button", { name: "send message" }).click();
    },
    settle: async (page) => {
      await expect(chatText(page, "not sent · tap to retry")).toBeVisible();
      await expect(
        bubble(page, "and book the table for friday at 8"),
      ).toBeVisible();
    },
  },
  "chat-has-more": {
    state: chatState(
      { events: LONG_HISTORY, cursor: OLDEST_LONG_ID },
      {
        routes: [
          {
            path: HISTORY_PATH,
            query: { cursor: String(OLDEST_LONG_ID) },
            json: { events: [], cursor: null },
          },
        ],
      },
    ),
    drive: async (page) => {
      await expect(bubble(page, "item 1 is on track")).toBeVisible(LOADED);
      await hoverMessageArea(page);
      await page.mouse.wheel(0, -600);
    },
    // The un-virtualized scroller keeps the top marker mounted, so "scrolled up"
    // is proven by the active scroll-to-latest button rather than the marker
    // leaving the DOM.
    settle: async (page) => {
      await expect(
        page
          .getByRole("button", { name: "Scroll to latest message" })
          .filter({ visible: true }),
      ).toHaveAttribute("data-active", "true");
    },
  },
  "chat-composer-typed": {
    state: chatState({ events: CONVERSATION }),
    drive: async (page) => {
      await expect(bubble(page, "moved to 4:30.")).toBeVisible(LOADED);
      await typeMessage(page, "and book the table for friday at 8");
    },
    settle: async (page) => {
      await expect(composer(page)).toHaveValue(
        "and book the table for friday at 8",
      );
      await expect(
        page.getByRole("button", { name: "send message" }),
      ).toBeEnabled();
    },
  },
  "chat-mobile-fullscreen": chatScenario(
    { events: CONVERSATION },
    async (page) => {
      await expect(bubble(page, "moved to 4:30.")).toBeVisible(LOADED);
      await expect(composer(page)).toBeVisible();
    },
  ),
  "logs-streaming": {
    state: logsState(logsRoute({ hang: true })),
    drive: () => Promise.resolve(),
    settle: async (page) => {
      await expect(page.getByText("streaming logs...")).toBeVisible(LOADED);
    },
  },
  "logs-lines": {
    state: logsState(LOG_LINES_ROUTE),
    drive: () => Promise.resolve(),
    settle: settleLogLines,
  },
  // The empty console's notice sits at the top of the scroll area, which the
  // full-screen navbar mask hides, so the settings tab console shows it.
  "logs-reconnecting": {
    state: logsState(
      logsRoute({ status: 500, body: "log stream failed" }),
      "settings",
    ),
    drive: async (page) => {
      await page.getByRole("tab", { name: "logs" }).click(LOADED);
    },
    settle: async (page) => {
      await expect(logText(page, "— reconnecting —")).toBeVisible(LOADED);
    },
  },
  "settings-logs-tab": {
    state: logsState(LOG_LINES_ROUTE, "settings"),
    drive: async (page) => {
      await page.getByRole("tab", { name: "logs" }).click(LOADED);
    },
    settle: settleLogLines,
  },

  "chat-attach-menu": {
    state: chatState({ events: CONVERSATION }),
    drive: async (page) => {
      await expect(composer(page)).toBeVisible(LOADED);
      await page
        .getByRole("button", { name: "add attachment" })
        .filter({ visible: true })
        .first()
        .click();
    },
    settle: async (page) => {
      await expect(
        page.getByRole("button", { name: "photos & videos" }).first(),
      ).toBeVisible(LOADED);
      await expect(
        page.getByRole("button", { name: "file", exact: true }).first(),
      ).toBeVisible();
    },
  },
  "chat-attachment-chips": {
    state: chatState(
      { events: CONVERSATION },
      { routes: attachmentRoutes(AGENT) },
    ),
    drive: async (page) => {
      await pickFiles(page, [
        SMALL_FILE,
        { ...SMALL_FILE, name: "summary.txt" },
      ]);
    },
    settle: async (page) => {
      await expect(chatText(page, "2 files ·").first()).toBeVisible(LOADED);
      await expect(
        page
          .getByPlaceholder("add a caption")
          .filter({ visible: true })
          .first(),
      ).toBeVisible();
    },
  },
  "chat-attachment-chip-uploading": {
    state: chatState(
      { events: CONVERSATION },
      { routes: attachmentRoutes(AGENT, { stallData: true }) },
    ),
    drive: async (page) => {
      await pickFiles(page, [SMALL_FILE]);
    },
    settle: async (page) => {
      await expect(chatText(page, "notes.txt").first()).toBeVisible(LOADED);
      await expect(
        page
          .getByRole("button", { name: "send message" })
          .filter({ visible: true })
          .first(),
      ).toBeDisabled();
    },
  },
  "chat-attachment-chip-error": {
    state: chatState(
      { events: CONVERSATION },
      { routes: attachmentRoutes(AGENT, { failCreate: true }) },
    ),
    drive: async (page) => {
      await pickFiles(page, [SMALL_FILE]);
    },
    settle: async (page) => {
      await expect(chatText(page, "upload failed").first()).toBeVisible(LOADED);
      await expect(
        page
          .getByRole("button", { name: "retry uploading notes.txt" })
          .filter({ visible: true })
          .first(),
      ).toBeVisible();
    },
  },
  "chat-attachment-chips-offline": {
    state: chatState(
      { events: CONVERSATION },
      { routes: attachmentRoutes(AGENT, { unreachableCreate: true }) },
    ),
    drive: async (page) => {
      await expect(composer(page)).toBeVisible(LOADED);
      await page.context().setOffline(true);
      await pickFiles(page, [SMALL_FILE]);
    },
    settle: async (page) => {
      await expect(chatText(page, "waiting for network").first()).toBeVisible(
        LOADED,
      );
    },
  },
  "chat-attachment-dropzone": {
    state: chatState({ events: CONVERSATION }),
    drive: async (page) => {
      // The dragenter bubbles from the visible composer up to its Chat card's
      // drop handlers, so the right instance overlays on every layout.
      await composer(page)
        .first()
        .evaluate((textarea) => {
          const transfer = new DataTransfer();
          transfer.items.add(
            new File(["x"], "drop.png", { type: "image/png" }),
          );
          textarea.dispatchEvent(
            new DragEvent("dragenter", {
              bubbles: true,
              dataTransfer: transfer,
            }),
          );
        });
    },
    settle: async (page) => {
      await expect(chatText(page, "drop to send to luna").first()).toBeVisible(
        LOADED,
      );
    },
  },
};
