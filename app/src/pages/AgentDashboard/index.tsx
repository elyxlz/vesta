import { useLayout } from "@/stores/use-layout";

import { useOutletContext } from "react-router-dom";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Card } from "@/components/ui/card";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import type { AgentHomeOutletContext } from "@/lib/types";

export function AgentDashboard() {
  const { chatCollapsed, setChatCollapsed } =
    useOutletContext<AgentHomeOutletContext>();
  const navbarHeight = useLayout((s) => s.navbarHeight);

  return (
    <div
      className="flex h-full w-full min-h-0 min-w-0 p-0 md:p-3"
      style={{
        paddingTop: `calc(${navbarHeight}px)`,
      }}
    >
      <ResizablePanelGroup
        orientation="horizontal"
        className="flex h-full w-full gap-2"
      >
        <ResizablePanel defaultSize="70%" minSize="300px">
          <div className="h-full">
            <Dashboard fullscreen />
          </div>
        </ResizablePanel>

        {!chatCollapsed && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize="30%" minSize="320px">
              <div className="h-full p-2">
                <Chat onCollapse={() => setChatCollapsed(true)} />
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>
    </div>
  );
}
