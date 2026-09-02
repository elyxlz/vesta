import { Activity, useEffect, useState } from "react";
import { Navigate, useLocation, useParams } from "react-router-dom";
import { AgentIslandModals } from "@/components/AgentIslandModals";
import { AgentNavbar } from "@/components/Navbar/AgentNavbar";
import { useIsMobile } from "@/hooks/use-mobile";
import { useOrbState } from "@/hooks/use-orb-state";
import { useSwipeNavigation } from "./use-swipe-navigation";
import { agentSubpage } from "@/lib/agent-subpage";
import {
  getChatCollapsed,
  setChatCollapsed as storeChatCollapsed,
} from "@/lib/chat-collapsed";
import { cn } from "@/lib/utils";
import { clearFaviconOrbState, setFaviconForOrbState } from "@/lib/favicon";
import { setLastAgent } from "@/lib/last-agent";
import { resetTabBaseTitle, setTabBaseTitle } from "@/lib/tab-title";
import { AgentLogs } from "@/pages/AgentLogs";
import { AgentSettingsPage } from "@/pages/AgentSettings";
import { useGateway } from "@/providers/GatewayProvider/context";
import { AgentLogStreamProvider } from "@/providers/AgentLogStreamProvider";
import { AgentSocketProvider } from "@/providers/AgentSocketProvider";
import { ModalsProvider } from "@/providers/ModalsProvider";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";
import { useSelectedAgent } from "@/providers/SelectedAgentProvider/context";
import { VoiceStoreEffects } from "@/providers/VoiceProvider";
import { DesktopPanelView } from "./DesktopPanelView";
import { MobileSwipeView } from "./MobileSwipeView";

export function AgentLayout() {
  const { name: routeName } = useParams<{ name: string }>();
  const { agents } = useGateway();
  const agent = agents.find((a) => a.name === routeName);
  const orbState = useOrbState(agent ?? null, agent?.activityState ?? "idle");

  useEffect(() => {
    if (!routeName) return;
    setTabBaseTitle(routeName);
    return () => resetTabBaseTitle();
  }, [routeName]);

  useEffect(() => {
    if (agent) setLastAgent(agent.name);
  }, [agent]);

  useEffect(() => {
    setFaviconForOrbState(orbState);
  }, [orbState]);

  useEffect(() => () => clearFaviconOrbState(), []);

  if (!agent) {
    return <Navigate to="/" replace />;
  }

  return (
    <SelectedAgentProvider agent={agent}>
      <AgentLayoutInner />
    </SelectedAgentProvider>
  );
}

function AgentLayoutInner() {
  const isMobile = useIsMobile();
  const { name } = useSelectedAgent();
  // The user's collapse choice persists per agent; the mobile swipe view forces
  // collapsed without storing it, so a phone-sized window never overwrites the
  // desktop preference. The choice made in this session is keyed by agent, so a
  // switch falls back to the stored preference instead of resetting from an effect.
  const [choice, setChoice] = useState<{
    name: string;
    collapsed: boolean;
  } | null>(null);
  const chatCollapsed =
    isMobile ||
    (choice !== null && choice.name === name
      ? choice.collapsed
      : getChatCollapsed(name));
  const { scrollRef, handleScroll, progress } = useSwipeNavigation();
  const subpage = agentSubpage(useLocation().pathname, name);

  const setChatCollapsed = (collapsed: boolean) => {
    setChoice({ name, collapsed });
    if (!isMobile) storeChatCollapsed(name, collapsed);
  };

  // Every pane stays mounted and navigation swaps visibility instead of
  // remounting: DOM, scroll, and component state survive the round trip.
  // Logs and settings hide in an Activity (display:none, effects unmounted);
  // the panel pane deliberately does not: the dashboard iframe is a composited
  // surface whose display:none teardown flashes black, and Activity's effect
  // cleanup would re-mint its service key and reload it. visibility hiding
  // skips painting, so the hidden panel costs only its JS.
  return (
    <VoiceStoreEffects>
      <AgentSocketProvider>
        <ModalsProvider>
          <AgentNavbar
            chatCollapsed={chatCollapsed}
            setChatCollapsed={setChatCollapsed}
            swipeProgress={progress}
          />
          <AgentLogStreamProvider>
            <div className="relative flex min-h-0 flex-1 flex-col">
              <div
                className={cn(
                  "absolute inset-0 flex flex-col",
                  subpage !== null && "invisible",
                )}
              >
                {isMobile ? (
                  <MobileSwipeView
                    scrollRef={scrollRef}
                    onScroll={handleScroll}
                  />
                ) : (
                  <DesktopPanelView
                    chatCollapsed={chatCollapsed}
                    setChatCollapsed={setChatCollapsed}
                  />
                )}
              </div>
              <Activity mode={subpage === "logs" ? "visible" : "hidden"}>
                <div className="absolute inset-0 flex flex-col">
                  <AgentLogs />
                </div>
              </Activity>
              <Activity mode={subpage === "settings" ? "visible" : "hidden"}>
                <div className="absolute inset-0 flex flex-col">
                  <AgentSettingsPage />
                </div>
              </Activity>
            </div>
          </AgentLogStreamProvider>
          <AgentIslandModals />
        </ModalsProvider>
      </AgentSocketProvider>
    </VoiceStoreEffects>
  );
}
