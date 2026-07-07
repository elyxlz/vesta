import { Console } from "@/components/Console";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

export function AgentLogs() {
  const { name, agent } = useSelectedAgent();

  return <Console name={name} status={agent.status} fullscreen />;
}
