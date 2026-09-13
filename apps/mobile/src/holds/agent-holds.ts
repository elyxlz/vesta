import {
  createKeyedHoldStore,
  type ChatState,
  type DraftAttachment,
  type KeyedHoldStore,
} from "@vesta/core";
import type { LogLine } from "@/agent/log-list-model";
import type { ReplyTarget } from "@/agent/message-actions";
import type { AgentPageKey } from "@/agent/pager-model";

// View state held ABOVE navigation and the controller epoch, so popping a screen, backgrounding,
// or a socket rebuild never resets what the user saw: the chat tail renders stale then reseeds,
// the composer keeps its half-typed draft and armed reply, the pager reopens on the last page, and
// the log buffer resumes. One keyed cell per concern. A conversation's cells (chat, composer,
// attachments) key by room; the pager and the log buffer are agent facts and key by agent.
export interface ComposerHold {
  draft: string;
  replyTarget: ReplyTarget | null;
}

export interface AgentHolds {
  chat: KeyedHoldStore<ChatState>;
  composer: KeyedHoldStore<ComposerHold>;
  attachments: KeyedHoldStore<DraftAttachment[]>;
  page: KeyedHoldStore<AgentPageKey>;
  logs: KeyedHoldStore<LogLine[]>;
}

export const agentHolds: AgentHolds = {
  chat: createKeyedHoldStore<ChatState>(),
  composer: createKeyedHoldStore<ComposerHold>(),
  attachments: createKeyedHoldStore<DraftAttachment[]>(),
  page: createKeyedHoldStore<AgentPageKey>(),
  logs: createKeyedHoldStore<LogLine[]>(),
};
