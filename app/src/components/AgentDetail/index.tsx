import { useEffect, useState } from "react";
import { PanelRightOpen } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
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

export function AgentDetail() {
  const { name, agent } = useSelectedAgent();
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
      {info?.alive ? (
        <ResizablePanelGroup orientation="horizontal">
          <ResizablePanel defaultSize={60} minSize="300px">
            <Card className="flex-1 flex flex-col min-w-0 h-full relative">
              <Dashboard />
            </Card>
          </ResizablePanel>

          {!chatCollapsed && (
            <>
              <ResizableHandle withHandle className="mx-2" />
              <ResizablePanel defaultSize={40} minSize="320px">
                <Chat onCollapse={() => setChatCollapsed(true)} />
              </ResizablePanel>
            </>
          )}

          {chatCollapsed && (
            <div className="shrink-0 flex items-start pt-2 justify-center pl-2">
              <Button
                size="icon-sm"
                variant="ghost"
                className="text-muted-foreground/60 hover:text-foreground"
                onClick={() => setChatCollapsed(false)}
              >
                <PanelRightOpen />
              </Button>
            </div>
          )}
        </ResizablePanelGroup>
      ) : (
        <Card className="flex-1 flex flex-col min-w-0 relative">
          <Dashboard />
        </Card>
      )}

      <AnimatePresence>
        {showConsole && info?.alive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-10"
            onClick={(e) => {
              if (e.target === e.currentTarget) setShowConsole(false);
            }}
          >
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="w-full h-full max-w-4xl dark dark-overlay bg-[#1a1a1a] text-[#e8e8e8] rounded-xl overflow-hidden shadow-2xl"
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
