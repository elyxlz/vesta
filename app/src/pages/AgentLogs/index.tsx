import { Console } from "@/components/Console";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function AgentLogs() {
  const { name } = useSelectedAgent();

  return (
    <div className="flex-1 min-h-0 relative">
      <Console name={name} fullscreen />
    </div>
  );
}
