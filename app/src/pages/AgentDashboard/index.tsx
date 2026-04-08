import { useOutletContext } from "react-router-dom";
import { AgentHome } from "@/components/AgentHome";
import { useLayout } from "@/stores/use-layout";
import type { AgentHomeOutletContext } from "@/lib/types";

export function AgentDashboard() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const { chatCollapsed } = useOutletContext<AgentHomeOutletContext>();

  return (
    <div
      className={`flex flex-col flex-1 min-h-0 relative overflow-hidden ${chatCollapsed ? "" : "px-page"}`}
      style={{ paddingTop: `calc(${navbarHeight}px + var(--page-padding-x) / 1.5)` }}
    >
      <AgentHome />
    </div>
  );
}
