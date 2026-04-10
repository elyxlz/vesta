import { useEffect, useState } from "react";
import { Navigate, Outlet, useParams } from "react-router-dom";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { AgentNavbar } from "@/components/AgentNavbar";
import { useIsMobile } from "@/hooks/use-mobile";
import { useGateway } from "@/providers/GatewayProvider";
import { ChatProvider } from "@/providers/ChatProvider";
import { ModalsProvider } from "@/providers/ModalsProvider";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";
import { VoiceProvider } from "@/providers/VoiceProvider";

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

  useEffect(() => {
    setChatCollapsed(isMobile);
  }, [isMobile]);

  return (
    <VoiceProvider>
      <ChatProvider>
        <ModalsProvider>
          <AgentNavbar
            chatCollapsed={chatCollapsed}
            setChatCollapsed={setChatCollapsed}
          />
          <Outlet context={{ chatCollapsed, setChatCollapsed }} />
          <AgentIslandModals />
        </ModalsProvider>
      </ChatProvider>
    </VoiceProvider>
  );
}
