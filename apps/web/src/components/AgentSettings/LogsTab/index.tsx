import { useNavigate } from "react-router-dom";
import { Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Console } from "@/components/Console";
import { useFillHeight } from "@/hooks/use-fill-height";
import { useIsMobile } from "@/hooks/use-mobile";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { cn } from "@/lib/utils";

// The Tabs container's pb-6 sits below the card, so reserve it when filling.
const BOTTOM_GAP = 24;

// Desktop: a fixed h-[70vh] matching the files tab. Mobile: fill the space left
// down to the viewport bottom (floored to a min by useFillHeight), since logs is
// the whole tab there.
export function LogsTab() {
  const navigate = useNavigate();
  const { name, agent } = useSelectedAgent();
  const isMobile = useIsMobile();
  const { ref, height } = useFillHeight(BOTTOM_GAP);

  return (
    <Card
      ref={isMobile ? ref : undefined}
      className={cn(
        "relative min-h-0 w-full !gap-0 !py-0",
        !isMobile && "h-[70vh]",
      )}
      style={isMobile ? { height } : undefined}
    >
      <Console name={name} status={agent.status} />
      <div className="absolute right-3 top-3 z-10">
        <Button
          variant="outline"
          size="icon"
          className="text-muted-foreground"
          aria-label="fullscreen logs"
          onClick={() => {
            void navigate(`/agent/${encodeURIComponent(name)}/logs`);
          }}
        >
          <Maximize2 />
        </Button>
      </div>
    </Card>
  );
}
