import { useState, type ReactNode } from "react";
import {
  initialChatState,
  seedTail,
  type ChatMessage,
  type ChatState,
} from "@vesta/core";
import {
  AgentHoldsContext,
  createAgentHolds,
  type AgentHolds,
} from "../../src/holds/AgentHoldsProvider";
import { agentHoldKey } from "../../src/holds/keyed-hold";
import { connectionKeyOf } from "../../src/session/session-model";
import { visualSwitch } from "./launch-query";
import { visualConnection } from "./session-provider";

export { useAgentHolds } from "../../src/holds/AgentHoldsProvider";

// visualChat picks aria's transcript: the default short exchange, `delivery`
// (a bubble still sending and one the gateway refused), `errors` (the snag and
// rate-limit lines), `markdown` (a rich reply), or `long` (days of history, for
// the scroll-to-bottom control and date headers).
const chatVariant = visualSwitch("visualChat");
const conversation: ChatMessage[] = [
    {
      id: 101,
      type: "user",
      text: "What should I focus on before tomorrow's product review?",
      ts: "2026-08-01T09:18:00.000Z",
    },
    {
      id: 102,
      type: "chat",
      text: "The onboarding polish and mobile QA gaps are the two items most likely to unblock the review.",
      ts: "2026-08-01T09:18:14.000Z",
    },
    {
      id: 103,
      type: "user",
      text: "Turn that into a short checklist.",
      ts: "2026-08-01T09:19:00.000Z",
    },
    {
      id: 104,
      type: "chat",
      text: "Done. I prioritized the visual regressions first, then the demo notes and follow-ups.",
      ts: "2026-08-01T09:19:11.000Z",
    },
    {
      id: 105,
      type: "user",
      text: "> Done. I prioritized the visual regressions first, then the demo notes and follow-ups.\n\nPerfect, let's start with the visual regressions.",
      ts: "2026-08-01T09:20:00.000Z",
    },
];
const deliveryTail: ChatMessage[] = [
  {
    type: "user",
    text: "Also book the room for Thursday.",
    ts: "2026-08-01T09:21:00.000Z",
    intent_id: "visual-sending",
    send_state: "sending",
  },
  {
    type: "user",
    text: "And send the agenda to the team.",
    ts: "2026-08-01T09:21:30.000Z",
    intent_id: "visual-failed",
    send_state: "failed",
  },
];
const errorTail: ChatMessage[] = [
  {
    id: 106,
    type: "user",
    text: "Summarise the launch thread.",
    ts: "2026-08-01T09:22:00.000Z",
  },
  {
    id: 107,
    type: "error",
    text: "turn failed",
    ts: "2026-08-01T09:22:05.000Z",
  },
  {
    id: 108,
    type: "rate_limited",
    text: "rate limited",
    window: "5h",
    resets_at: Date.UTC(2026, 7, 1, 11, 0),
    ts: "2026-08-01T09:22:06.000Z",
  },
];
const markdownTail: ChatMessage[] = [
  {
    id: 109,
    type: "user",
    text: "How do I rotate the gateway key?",
    ts: "2026-08-01T09:23:00.000Z",
  },
  {
    id: 110,
    type: "chat",
    text: [
      "## Rotating the key",
      "",
      "1. Open **Settings**, then **Gateway**.",
      "2. Run the rotate command:",
      "",
      "```bash",
      "vestad rotate-key --confirm",
      "```",
      "",
      "- Every client needs the new connect link.",
      "- Old links stop working at once.",
      "",
      "Details in the [gateway guide](https://vesta.run/docs/gateway).",
    ].join("\n"),
    ts: "2026-08-01T09:23:20.000Z",
  },
];
const longHistory: ChatMessage[] = Array.from({ length: 40 }, (_, index) => {
  const day = 25 + Math.floor(index / 8);
  const minute = (index % 8) * 7;
  const user = index % 2 === 0;
  return {
    id: 200 + index,
    type: user ? "user" : "chat",
    text: user
      ? `Status check ${index / 2 + 1}: anything new on the launch?`
      : "Nothing blocking. Two reviews merged, one waiting on design.",
    ts: new Date(Date.UTC(2026, 6, day, 9, minute)).toISOString(),
  };
});
const events: ChatMessage[] =
  chatVariant === "delivery"
    ? [...conversation, ...deliveryTail]
    : chatVariant === "errors"
      ? [...conversation, ...errorTail]
      : chatVariant === "markdown"
        ? [...conversation, ...markdownTail]
        : chatVariant === "long"
          ? [...longHistory, ...conversation]
          : conversation;
const chatState: ChatState = seedTail(initialChatState(), {
  events,
  cursor: null,
});

function createVisualAgentHolds(): AgentHolds {
  const holds = createAgentHolds();
  const connectionKey = connectionKeyOf(visualConnection) ?? "";
  holds.chat.persist(agentHoldKey("aria", connectionKey), chatState);
  // nova has history loaded and no messages, so opening nova renders the empty-chat state.
  holds.chat.persist(
    agentHoldKey("nova", connectionKey),
    seedTail(initialChatState(), { events: [], cursor: null }),
  );
  return holds;
}

export function AgentHoldsProvider({ children }: { children: ReactNode }) {
  const [holds] = useState(createVisualAgentHolds);
  return (
    <AgentHoldsContext.Provider value={holds}>
      {children}
    </AgentHoldsContext.Provider>
  );
}
