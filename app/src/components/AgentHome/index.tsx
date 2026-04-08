import { useOutletContext } from "react-router-dom";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import type { AgentHomeOutletContext } from "@/lib/types";

export function AgentHome() {
  const { chatCollapsed, setChatCollapsed } = useOutletContext<AgentHomeOutletContext>();

  return (
    <div className="flex h-full w-full min-h-0 min-w-0">
      <ResizablePanelGroup orientation="horizontal" className="flex h-full w-full">
        <ResizablePanel defaultSize="70%" minSize="300px">
          <div className={`flex-1 flex flex-col min-w-0 h-full relative${chatCollapsed ? "" : " pr-1.5"}`}>
            <Dashboard fullscreen={chatCollapsed} />
          </div>
        </ResizablePanel>

        {!chatCollapsed && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="30%" minSize="320px">
              <div className="h-full pb-page pl-2">
                <Chat onCollapse={() => setChatCollapsed(true)} />
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
    </div>
  );
}
