import {
  createContext,
  use,
  useCallback,
  useEffect,
  useMemo,
  type ReactNode,
} from "react";
import { useLocalSearchParams } from "expo-router";
import { ChatContext, type ChatContextValue } from "@/chat/chat-context";
import { useRoomSocket, type RoomSocket } from "@/chat/useRoomSocket";
import { ControllerContext } from "@/controller/context";
import { useRoster } from "@/session/RosterProvider";
import { useReplica } from "@vesta/core/react";
import {
  directRoomId,
  type AgentActivityState,
  type AgentRow,
  type Tree,
} from "@vesta/core";
import { writeLastUsedAgent } from "@/storage/recent-agent";
import {
  agentActivitySnapshotsEqual,
  selectAgentActivitySnapshot,
  servedAgentActivity,
} from "@/chat/agent-activity-model";

interface AgentValue {
  name: string;
  agent: AgentRow | null;
  activityState: AgentActivityState;
  // The ids of the notifications this agent has not worked through yet.
  pendingNotifications: string[];
  socket: RoomSocket;
}

const AgentContext = createContext<AgentValue | null>(null);

function idsEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

// The provider and socket hook stay mounted across controller epochs. Backgrounding disables the
// live edges without replacing the nested navigation tree, so an open agent sheet retains its state.
// It serves two contexts: the agent facts every page of the pager reads, and the chat context for
// this agent's own direct room, which is the conversation its chat page shows.
export function AgentProvider({ children }: { children: ReactNode }) {
  const parameters = useLocalSearchParams<{ name?: string }>();
  const name = typeof parameters.name === "string" ? parameters.name : "";
  const controller = use(ControllerContext);
  const { agents } = useRoster();
  const agent = agents.find((candidate) => candidate.name === name) ?? null;
  const roomId = directRoomId(name);
  const socket = useRoomSocket(name ? roomId : "", name || null, controller);
  const replica = controller?.replica ?? null;

  const activitySelector = useCallback(
    (tree: Tree | null) =>
      selectAgentActivitySnapshot(tree, Boolean(name), name),
    [name],
  );
  const activity = useReplica(
    replica,
    activitySelector,
    agentActivitySnapshotsEqual,
  );
  const pendingSelector = useCallback(
    (tree: Tree | null): string[] =>
      name
        ? (tree?.agents[name]?.notifications.pending ?? []).flatMap((notif) =>
            notif.notif_id ? [notif.notif_id] : [],
          )
        : [],
    [name],
  );
  const pendingNotifications = useReplica(replica, pendingSelector, idsEqual);
  const activityState = servedAgentActivity(activity, agent?.activityState);

  useEffect(() => {
    if (name) void writeLastUsedAgent(name);
  }, [name]);

  // Memoized (with the socket hook's own memoized return) so the four always-mounted agent pages
  // re-render only when a consumed field changes, not on every provider render.
  const value = useMemo(
    () => ({ name, agent, activityState, pendingNotifications, socket }),
    [name, agent, activityState, pendingNotifications, socket],
  );
  const chat = useMemo<ChatContextValue>(
    () => ({
      roomId,
      label: name,
      agents: [name],
      kind: "direct",
      agent,
      socket,
    }),
    [roomId, name, agent, socket],
  );

  return (
    <AgentContext.Provider value={value}>
      <ChatContext.Provider value={chat}>{children}</ChatContext.Provider>
    </AgentContext.Provider>
  );
}

export function useAgent(): AgentValue {
  const value = use(AgentContext);
  if (!value) throw new Error("useAgent must be used within AgentProvider");
  return value;
}
