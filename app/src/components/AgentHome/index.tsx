import { AgentHomeDesktop } from "./AgentHomeDesktop";
import { AgentHomeMobile } from "./AgentHomeMobile";

export function AgentHome() {
  return (
    <div className="flex h-full relative overflow-hidden">
      <AgentHomeDesktop />
      <AgentHomeMobile />
    </div>
  );
}
