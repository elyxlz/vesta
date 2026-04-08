import { AgentSettings } from "@/components/AgentSettings";
import { useLayout } from "@/stores/use-layout";

export function AgentSettingsPage() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div className="flex flex-col flex-1 min-h-0 px-page" style={{ paddingTop: navbarHeight }}>
      <AgentSettings />
    </div>
  );
}
