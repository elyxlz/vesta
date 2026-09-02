import { Server } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { AgentServicesList } from "@/components/AgentServices";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";

export function ServicesCard() {
  const { name } = useSelectedAgent();
  const who = name || "the agent";

  return (
    <div className="flex flex-col gap-2">
      <Card size="sm">
        <CardHeader>
          <CardTitle>
            <Server className="size-4 text-muted-foreground" />
            services
          </CardTitle>
          <CardDescription>
            the small apps {who} runs for you, each at its own address.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AgentServicesList />
        </CardContent>
      </Card>
      <p className="px-4 text-sm text-muted-foreground">
        the small apps {who} runs for you: live tools, dashboards, and
        integrations, each reachable at its own address. ask {who} in chat what
        one does, or to build, change, or stop one.
      </p>
    </div>
  );
}
