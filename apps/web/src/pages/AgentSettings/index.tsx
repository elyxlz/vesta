import { AgentSettings } from "@/components/AgentSettings";

// The sidebar stays fixed while the active section scrolls under the navbar in
// its own faded PageScroll container (see AgentSettings).
export function AgentSettingsPage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AgentSettings />
    </div>
  );
}
