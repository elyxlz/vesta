import { createContext, use, useState, type ReactNode } from "react";
import type { ChatState } from "@vesta/core";
import type { LogLine } from "@/agent/log-list-model";
import type { ReplyTarget } from "@/agent/message-actions";
import type { AgentPageKey } from "@/agent/pager-model";
import { createKeyedHoldStore, type KeyedHoldStore } from "./keyed-hold";

// Per-agent view state held ABOVE navigation and the controller epoch, so popping the agent
// screen, backgrounding, or a socket rebuild never resets what the user saw: the chat tail
// renders stale then reseeds, the composer keeps its half-typed draft and armed reply, the pager
// reopens on the last page, and the log buffer resumes. One keyed cell per concern.
export interface ComposerHold {
  draft: string;
  replyTarget: ReplyTarget | null;
}

export interface LogsHold {
  lines: LogLine[];
  nextId: number;
}

export interface AgentHolds {
  chat: KeyedHoldStore<ChatState>;
  composer: KeyedHoldStore<ComposerHold>;
  page: KeyedHoldStore<AgentPageKey>;
  logs: KeyedHoldStore<LogsHold>;
}

export function createAgentHolds(): AgentHolds {
  return {
    chat: createKeyedHoldStore<ChatState>(),
    composer: createKeyedHoldStore<ComposerHold>(),
    page: createKeyedHoldStore<AgentPageKey>(),
    logs: createKeyedHoldStore<LogsHold>(),
  };
}

const AgentHoldsContext = createContext<AgentHolds | null>(null);

export function AgentHoldsProvider({ children }: { children: ReactNode }) {
  const [holds] = useState(createAgentHolds);
  return (
    <AgentHoldsContext.Provider value={holds}>
      {children}
    </AgentHoldsContext.Provider>
  );
}

export function useAgentHolds(): AgentHolds {
  const holds = use(AgentHoldsContext);
  if (!holds) {
    throw new Error("useAgentHolds must be used within AgentHoldsProvider");
  }
  return holds;
}
