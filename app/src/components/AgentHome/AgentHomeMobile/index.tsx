import { Dashboard } from "@/components/Dashboard";

export function AgentHomeMobile() {
  return (
    <div className="flex md:hidden h-full w-full min-h-0 min-w-0 pt-4">
      <div className="flex-1 flex flex-col min-w-0 min-h-0 relative">
        <Dashboard />
      </div>
    </div>
  );
}
