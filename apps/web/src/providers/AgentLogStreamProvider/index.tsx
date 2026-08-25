import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { streamLogs, stopLogs } from "@/api";
import { renderAnsiHtml } from "@/lib/ansi-html";
import { linkify } from "@/lib/linkify";
import { createLogSession, type LogSession } from "@/lib/log-session";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

const AgentLogSessionContext = createContext<LogSession | null>(null);

function makeSession(name: string): LogSession {
  return createLogSession({
    name,
    streamLogs,
    stopLogs,
    renderLine: (text) => renderAnsiHtml(text, linkify),
  });
}

// The layout-level owner of the selected agent's log stream. It lives above the
// AgentLayout Activity panes, so the stream a log viewer started stays connected
// and keeps accumulating while the viewer is hidden; it dies with the layout, so
// leaving the agent closes it. The stream is lazy: nothing connects until a
// viewer calls start().
export function AgentLogStreamProvider({ children }: { children: ReactNode }) {
  const { name, agent } = useSelectedAgent();
  const [held, setHeld] = useState(() => ({
    name,
    session: makeSession(name),
  }));
  // Render-phase reset on agent switch: React re-renders before committing, so
  // children only ever see the session matching the selected agent.
  if (held.name !== name) {
    setHeld({ name, session: makeSession(name) });
  }
  const session = held.session;

  useEffect(() => () => session.dispose(), [session]);

  useEffect(() => {
    session.setStatus(agent.status);
  }, [session, agent.status]);

  return (
    <AgentLogSessionContext.Provider value={session}>
      {children}
    </AgentLogSessionContext.Provider>
  );
}

export function useAgentLogSession(): LogSession {
  const session = useContext(AgentLogSessionContext);
  if (!session) {
    throw new Error(
      "useAgentLogSession must be used within AgentLogStreamProvider",
    );
  }
  return session;
}
