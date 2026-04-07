import { useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { KeyRound, Minimize2, Wrench } from "lucide-react";
import { Chat } from "@/components/Chat";
import { AgentIsland } from "@/components/AgentIsland";
import { AgentMenu } from "@/components/AgentMenu";
import { Navbar } from "@/components/Navbar";
import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { useIsMobile } from "@/hooks/use-mobile";
import { useAgentIslandContext } from "@/lib/AgentLayout";
import { useLayout } from "@/stores/use-layout";
import { cn } from "@/lib/utils";

export function AgentChat() {
  const navigate = useNavigate();
  const { name } = useParams<{ name: string }>();
  const [showToolCalls, setShowToolCalls] = useState(false);
  const island = useAgentIslandContext();
  const isMobile = useIsMobile();
  const showMobileReauth = isMobile && island.info?.status === "running" && !island.info?.authenticated;
  const headerStripRef = useRef<HTMLDivElement>(null);
  const setChatHeaderStripBottomPx = useLayout((s) => s.setChatHeaderStripBottomPx);

  useLayoutEffect(() => {
    const el = headerStripRef.current;
    if (!el) return;
    const update = () => {
      setChatHeaderStripBottomPx(Math.ceil(el.getBoundingClientRect().bottom));
    };
    const ro = new ResizeObserver(update);
    ro.observe(el);
    update();
    window.addEventListener("resize", update);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
      setChatHeaderStripBottomPx(0);
    };
  }, [setChatHeaderStripBottomPx]);

  return (
    <div className="h-full relative">
      <div
        ref={headerStripRef}
        className="absolute top-0 left-0 right-0 z-10 px-3 sm:px-5 pointer-events-none"
      >
        <div className="pointer-events-auto">
          <Navbar
            center={
              <>
                <AgentIsland {...island} />
                {showMobileReauth && (
                  <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2">
                    <Button size="sm" onClick={() => void island.handleOpenAuth()}>
                      <KeyRound data-icon="inline-start" />
                      reauthenticate
                    </Button>
                  </div>
                )}
              </>
            }
            trailing={
              <div data-agent-menu className="flex items-center">
                <AgentMenu
                  open={island.menuOpen}
                  onOpenChange={island.onMenuOpenChange}
                  name={island.name}
                  info={island.info}
                  isBusy={island.isBusy}
                  authenticateBesideTrigger
                  onAuthOpen={island.handleOpenAuth}
                  onStart={island.start}
                  onStop={island.stop}
                  onRestart={island.restart}
                  onRebuild={island.rebuild}
                  onBackup={island.backup}
                  onShowBackups={island.onShowBackups}
                  onShowConsole={island.onShowConsole}
                  onShowAgentSettings={island.onShowAgentSettings}
                  onOpenDeleteDialog={island.onOpenDeleteDialog}
                />
              </div>
            }
          />
        </div>
        <div className="flex justify-end pointer-events-auto mt-1">
          <ButtonGroup>
            <Button
              size="icon-sm"
              variant="outline"
              className="md:size-9"
              onClick={() => navigate(`/agent/${name}`)}
            >
              <Minimize2 />
            </Button>
            <Button
              size="icon-sm"
              variant="outline"
              className={cn(
                "md:size-9",
                showToolCalls ? "text-primary" : "text-muted-foreground",
              )}
              aria-pressed={showToolCalls}
              onClick={() => setShowToolCalls((v) => !v)}
            >
              <Wrench />
            </Button>
          </ButtonGroup>
        </div>
      </div>
      <Chat fullscreen showToolCalls={showToolCalls} />
    </div>
  );
}
