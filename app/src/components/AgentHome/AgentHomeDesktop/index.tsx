import { useOutletContext } from "react-router-dom";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import type { AgentHomeOutletContext } from "@/lib/types";

export function AgentHomeDesktop() {
  const { chatCollapsed, setChatCollapsed } = useOutletContext<AgentHomeOutletContext>();

  return (
    <div className="hidden md:flex h-full w-full min-h-0 min-w-0">
      <ResizablePanelGroup orientation="horizontal" className="flex h-full w-full gap-3">
        <ResizablePanel defaultSize="70%" minSize="300px">
          <div className="flex-1 flex flex-col min-w-0 h-full relative pt-5">
            <Dashboard />
          </div>
        </ResizablePanel>

        {!chatCollapsed && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="30%" minSize="320px" className="py-5">
              <Chat onCollapse={() => setChatCollapsed(true)} />
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
    </div>
  );
}
