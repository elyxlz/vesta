import { AgentHome } from "@/components/AgentHome";
import { useLayout } from "@/stores/use-layout";
import { useIsMobile } from "@/hooks/use-mobile";

export function AgentDashboard() {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const isMobile = useIsMobile();

  return (
    <div
      className={`flex flex-col flex-1 min-h-0 relative overflow-hidden ${isMobile ? "" : "px-page"}`}
      style={{ paddingTop: navbarHeight }}
    >
      <AgentHome />
    </div>
  );
}
