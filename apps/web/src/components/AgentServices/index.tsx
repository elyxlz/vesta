import { Globe } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

// Read-only view of the agent's registered services, shared by the agent-menu
// dialog and the settings card. Live from the /sync roster, so rows appear and
// disappear as services register and unregister.
export function AgentServicesList() {
  const { agent } = useSelectedAgent();
  const rows = Object.entries(agent.services)
    .map(([service, info]) => ({
      name: service,
      public: info.public,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="flex flex-col gap-3">
      {rows.length === 0 ? (
        <p className="text-base text-muted-foreground">no services yet</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((row) => (
            <li
              key={row.name}
              className="flex items-center justify-between gap-3 rounded-md bg-muted/50 px-3 py-2"
            >
              <span className="flex min-w-0 items-center gap-2 text-base">
                <Globe className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">{row.name}</span>
              </span>
              <Badge
                variant={row.public ? "outline" : "secondary"}
                className="shrink-0"
              >
                {row.public ? "public" : "private"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
