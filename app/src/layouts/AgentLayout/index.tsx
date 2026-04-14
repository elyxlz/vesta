import { useEffect, useState } from "react";
import { Navigate, Outlet, useParams } from "react-router-dom";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { AgentNavbar } from "@/components/Navbar/AgentNavbar";
import { useIsMobile } from "@/hooks/use-mobile";
import { useSwipeNavigation } from "@/hooks/use-swipe-navigation";
import { useGateway } from "@/providers/GatewayProvider";
import { ChatProvider } from "@/providers/ChatProvider";
import { ModalsProvider } from "@/providers/ModalsProvider";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";
import { VoiceStoreEffects } from "@/providers/VoiceProvider";
import { DesktopPanelView } from "./DesktopPanelView";
import { MobileSwipeView } from "./MobileSwipeView";

export function AgentLayout() {
  const { name: routeName } = useParams<{ name: string }>();
  const { agents } = useGateway();
  const agent = agents.find((a) => a.name === routeName);

  if (!agent) {
    return <Navigate to="/home" replace />;
  }

  return (
    <SelectedAgentProvider agent={agent}>
      <AgentLayoutInner />
    </SelectedAgentProvider>
  );
}

function AgentLayoutInner() {
  const isMobile = useIsMobile();
  const [chatCollapsed, setChatCollapsed] = useState(isMobile);
  const { scrollRef, handleScroll, progress, isSubpage } = useSwipeNavigation();

  useEffect(() => {
    setChatCollapsed(isMobile);
  }, [isMobile]);

  return (
    <VoiceStoreEffects>
      <ChatProvider>
        <ModalsProvider>
          <AgentNavbar
            chatCollapsed={chatCollapsed}
            setChatCollapsed={setChatCollapsed}
            swipeProgress={progress}
          />
          {isSubpage ? (
            <div className="flex flex-col flex-1 min-h-0">
              <Outlet />
            </div>
          ) : isMobile ? (
            <MobileSwipeView scrollRef={scrollRef} onScroll={handleScroll} />
          ) : (
            <DesktopPanelView
              chatCollapsed={chatCollapsed}
              setChatCollapsed={setChatCollapsed}
            />
          )}
          <AgentIslandModals />
        </ModalsProvider>
      </ChatProvider>
    </VoiceStoreEffects>
  );
}
