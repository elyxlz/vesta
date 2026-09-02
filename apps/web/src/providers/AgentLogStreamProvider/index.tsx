import { useEffect, useState, type ReactNode } from "react";
import { streamLogs, stopLogs } from "@/api";
import { renderAnsiHtml } from "@/lib/ansi-html";
import { linkify } from "@/lib/linkify";
import { createLogSession, type LogSession } from "@/lib/log-session";
import { isAgentContainerUp } from "@/lib/log-stream-policy";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { AgentLogSessionContext } from "./context";

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
// leaving the agent closes it. The stream is warmed as soon as the agent's
// container is up, so opening the log view renders an already-filled buffer; a
// stopped agent stays lazy (its one-shot dump reads the whole log file
// server-side) and streams only when a viewer calls start().
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

  useEffect(() => {
    if (isAgentContainerUp(agent.status)) session.start();
  }, [session, agent.status]);

  return (
    <AgentLogSessionContext.Provider value={session}>
      {children}
    </AgentLogSessionContext.Provider>
  );
}
