import { AgentHome } from "@/components/AgentHome";
import { UpdateBar } from "@/components/UpdateBar";
import { useAuth } from "@/providers/AuthProvider";

export function AgentDashboard() {
  const { connected } = useAuth();

  return (
    <div className="flex flex-col flex-1 min-h-0 gap-3 md:gap-4 px-3 pb-3 sm:px-5 sm:pb-5">
      {connected && (
        <div className="shrink-0">
          <UpdateBar />
        </div>
      )}
      <div className="flex-1 relative overflow-hidden min-h-0">
        <AgentHome />
      </div>
    </div>
  );
}
