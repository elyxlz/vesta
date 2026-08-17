import { useState, type ReactNode } from "react";
import {
  initialChatState,
  seedTail,
  type ChatState,
} from "@vesta/core";
import {
  AgentHoldsContext,
  createAgentHolds,
  type AgentHolds,
} from "../../src/holds/AgentHoldsProvider";
import { agentHoldKey } from "../../src/holds/keyed-hold";
import { connectionKeyOf } from "../../src/session/session-model";
import { visualConnection } from "./session-provider";

export { useAgentHolds } from "../../src/holds/AgentHoldsProvider";

const chatState: ChatState = seedTail(initialChatState(), {
  events: [
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
  ],
  cursor: null,
});

function createVisualAgentHolds(): AgentHolds {
  const holds = createAgentHolds();
  holds.chat.persist(
    agentHoldKey("aria", connectionKeyOf(visualConnection) ?? ""),
    chatState,
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
