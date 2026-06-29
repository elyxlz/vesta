import { AgentSettings } from "@/components/AgentSettings";
import { useLayout } from "@/stores/use-layout";

// The page itself doesn't scroll — the tab row stays fixed and the active tab's
// content scrolls inside its own faded container (see AgentSettings).
export function AgentSettingsPage() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div
      className="flex min-h-0 flex-1 flex-col"
      style={{ paddingTop: navbarHeight }}
    >
      <AgentSettings />
    </div>
  );
}
