import { AgentSettings } from "@/components/AgentSettings";
import { NavbarScrim } from "@/components/NavbarScrim";
import { useLayout } from "@/stores/use-layout";

export function AgentSettingsPage() {
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <>
      <NavbarScrim />
      <div
        className="flex flex-col flex-1 min-h-0 overflow-y-auto px-page"
        style={{ paddingTop: navbarHeight }}
      >
        <AgentSettings />
      </div>
    </>
  );
}
