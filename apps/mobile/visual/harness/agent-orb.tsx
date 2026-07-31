import type { ComponentProps } from "react";
import { AgentOrb as AppAgentOrb } from "../../src/components/AgentOrb";

type AgentOrbProps = ComponentProps<typeof AppAgentOrb>;

export function AgentOrb(props: AgentOrbProps) {
  return <AppAgentOrb {...props} animated={false} />;
}
