import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";

export function AgentHome() {
  const { name } = useSelectedAgent();
  const navigate = useNavigate();
  const [chatCollapsed, setChatCollapsed] = useState(false);

  return (
    <div className="flex h-full relative overflow-hidden">
      <div className="hidden md:flex h-full w-full min-h-0 min-w-0">
        <ResizablePanelGroup orientation="horizontal" className="flex h-full w-full">
          <ResizablePanel defaultSize="70%" minSize="300px">
            <Card className="flex-1 flex flex-col min-w-0 h-full relative">
              {chatCollapsed && (
                <div className="absolute top-2 right-2 z-10">
                  <ButtonGroup>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setChatCollapsed(false)}
                    >
                      <MessageSquare />
                      Chat
                    </Button>
                  </ButtonGroup>
                </div>
              )}
              <Dashboard />
            </Card>
          </ResizablePanel>

          {!chatCollapsed && (
            <>
              <ResizableHandle withHandle className="mx-2" />
              <ResizablePanel defaultSize="30%" minSize="320px">
                <Chat onCollapse={() => setChatCollapsed(true)} />
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>
      </div>

      <div className="flex md:hidden h-full w-full min-h-0 min-w-0">
        <Card className="flex-1 flex flex-col min-w-0 min-h-0 relative">
          <div className="absolute top-2 right-2 z-10">
            <ButtonGroup>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/agent/${name}/chat`)}
              >
                <MessageSquare />
                Chat
              </Button>
            </ButtonGroup>
          </div>
          <Dashboard />
        </Card>
      </div>

    </div>
  );
}
