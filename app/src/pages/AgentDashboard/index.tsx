import { AgentHome } from "@/components/AgentHome";
import { useLayout } from "@/stores/use-layout";

export function AgentDashboard() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div
      className="flex flex-col flex-1 min-h-0 relative overflow-hidden px-page"
      style={{ paddingTop: navbarHeight }}
    >
      <AgentHome />
    </div>
  );
}
