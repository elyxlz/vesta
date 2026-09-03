export type AgentSubpage = "logs" | "settings" | null;

// Which full-screen subpage of /agent/:name the location shows; null is the
// dashboard/chat panel. Drives the AgentLayout Activity panes, which keep every
// pane mounted and toggle only visibility.
export function agentSubpage(pathname: string, name: string): AgentSubpage {
  const base = `/agent/${encodeURIComponent(name)}`;
  if (pathname === `${base}/logs`) return "logs";
  if (pathname === `${base}/settings`) return "settings";
  return null;
}
