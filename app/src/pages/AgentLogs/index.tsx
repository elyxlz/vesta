import { Console } from "@/components/Console";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function AgentLogs() {
  const { name } = useSelectedAgent();

  return (
      <Console name={name} fullscreen />
  );
}
