import { Maximize2, PanelRightClose } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";

interface ChatHeaderActionsProps {
  fullscreen?: boolean;
  onCollapse?: () => void;
  agentName: string;
}

export function ChatHeaderActions({
  fullscreen,
  onCollapse,
  agentName,
}: ChatHeaderActionsProps) {
  const navigate = useNavigate();

  if (fullscreen) return null;

  return (
    <div className="absolute right-3 top-3 z-10">
      <ButtonGroup>
        <Button
          variant="outline"
          className="text-muted-foreground"
          onClick={() => navigate(`/agent/${agentName}/chat`)}
        >
          <Maximize2 />
        </Button>
        <Button
          variant="outline"
          className="text-muted-foreground"
          onClick={onCollapse}
        >
          <PanelRightClose />
        </Button>
      </ButtonGroup>
    </div>
  );
}
