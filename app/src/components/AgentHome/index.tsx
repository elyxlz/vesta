import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquare } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { Chat } from "@/components/Chat";
import { Console } from "@/components/Console";
import { Dashboard } from "@/components/Dashboard";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider";
import { useAgents } from "@/providers/AgentsProvider";

export function AgentHome() {
  const { name, agent } = useSelectedAgent();
  const navigate = useNavigate();
  const { agents } = useAgents();
  const listEntry = agents.find((a) => a.name === name);

  const [showConsole, setShowConsole] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const info = agent ?? listEntry ?? null;

  useEffect(() => {
    const handleOpenConsole = () => setShowConsole(true);
    window.addEventListener("open-console", handleOpenConsole);
    return () => window.removeEventListener("open-console", handleOpenConsole);
  }, []);

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

      <AnimatePresence>
        {showConsole && info?.alive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 flex items-stretch md:items-center justify-center bg-black/60 backdrop-blur-sm p-0 md:p-10"
            onClick={(e) => {
              if (e.target === e.currentTarget) setShowConsole(false);
            }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="flex min-h-0 min-w-0 flex-1 flex-col md:h-auto md:max-h-[calc(100vh-5rem)] md:max-w-4xl md:flex-none dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8] rounded-none md:rounded-xl overflow-hidden shadow-2xl"
            >
              <Console
                name={name}
                onClose={() => setShowConsole(false)}
              />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
