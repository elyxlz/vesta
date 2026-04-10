import { useGateway } from "@/providers/GatewayProvider";
import { AgentsCarousel } from "./AgentsCarousel";
import { EmptyState } from "./EmptyState";

export function Home() {
  const { agents } = useGateway();

  if (agents.length === 0) return <EmptyState />;

  return <AgentsCarousel agents={agents} />;
}
