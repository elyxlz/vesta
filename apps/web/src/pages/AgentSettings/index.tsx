import { AgentSettings } from "@/components/AgentSettings";
import { useLayout } from "@/stores/use-layout";
import { navbarFadeMask } from "@/lib/navbar-fade";

export function AgentSettingsPage() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div
      className="flex flex-col flex-1 min-h-0 overflow-y-auto px-page"
      style={{ paddingTop: navbarHeight, ...navbarFadeMask(navbarHeight) }}
    >
      <AgentSettings />
    </div>
  );
}
