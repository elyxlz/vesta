import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Minimize2, Wrench } from "lucide-react";
import { Chat } from "@/components/Chat";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { cn } from "@/lib/utils";

export function AgentChat() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const [showToolCalls, setShowToolCalls] = useState(false);

  return (
    <div className="flex-1 min-h-0 relative">
      <div className="absolute top-2 right-3 sm:right-5 z-10">
        <ButtonGroup>
          <Button
            size="icon-sm"
            variant="outline"
            className={cn(
              "md:size-9",
              showToolCalls ? "text-primary" : "text-muted-foreground",
            )}
            onClick={() => navigate(`/agent/${name}`)}
          >
            <Minimize2 />
          </Button>
          <Button
            size="icon-sm"
            variant="outline"
            className={cn(
              "md:size-9",
              showToolCalls ? "text-primary" : "text-muted-foreground",
            )}
            aria-pressed={showToolCalls}
            onClick={() => setShowToolCalls((v) => !v)}
          >
            <Wrench />
          </Button>
        </ButtonGroup>
      </div>
      <Chat fullscreen showToolCalls={showToolCalls} />
    </div>
  );
}
