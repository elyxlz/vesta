import { Globe } from "lucide-react";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";

// Read-only view of the agent's registered services, shared by the agent-menu
// dialog and the settings card. Live from the /sync roster, so rows appear and
// disappear as services register and unregister.
export function AgentServicesList() {
  const { name, agent } = useSelectedAgent();
  const rows = Object.entries(agent.services)
    .map(([service, info]) => ({ name: service, port: info.port }))
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="flex flex-col gap-3">
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">no services yet</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {rows.map((row) => (
            <li
              key={row.name}
              className="flex items-center justify-between gap-3 rounded-md bg-muted/50 px-3 py-2"
            >
              <span className="flex min-w-0 items-center gap-2 text-sm">
                <Globe className="size-4 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium">{row.name}</span>
              </span>
              <span className="shrink-0 font-mono text-xs text-muted-foreground">
                :{row.port}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        these are the small apps {name} runs for you. ask {name} in chat what
        each one does.
      </p>
    </div>
  );
}
