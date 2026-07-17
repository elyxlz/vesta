import type { Dispatch, SetStateAction } from "react";
import { useLocation, useParams } from "react-router-dom";
import { useDefaultLayout } from "react-resizable-panels";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { Chat } from "@/components/Chat";
import { Dashboard } from "@/components/Dashboard";
import { useLayout } from "@/stores/use-layout";

const DASHBOARD_CHAT_LAYOUT_ID = "agent-dashboard-chat";
const DASHBOARD_PANEL_ID = "dashboard";
const CHAT_PANEL_ID = "chat";
// The panel id set keys the stored layout, so collapsed and expanded persist separately.
const COLLAPSED_PANEL_IDS = [DASHBOARD_PANEL_ID];
const EXPANDED_PANEL_IDS = [DASHBOARD_PANEL_ID, CHAT_PANEL_ID];

interface DesktopPanelViewProps {
  chatCollapsed: boolean;
  setChatCollapsed: Dispatch<SetStateAction<boolean>>;
}

export function DesktopPanelView({
  chatCollapsed,
  setChatCollapsed,
}: DesktopPanelViewProps) {
  const navbarHeight = useLayout((s) => s.navbarHeight);
  const { name } = useParams<{ name: string }>();
  const location = useLocation();
  const isChat =
    location.pathname === `/agent/${encodeURIComponent(name ?? "")}/chat`;

  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: DASHBOARD_CHAT_LAYOUT_ID,
    panelIds: chatCollapsed ? COLLAPSED_PANEL_IDS : EXPANDED_PANEL_IDS,
    onlySaveAfterUserInteractions: true,
  });

  if (isChat) {
    return <Chat fullscreen />;
  }

  return (
    <div
      className="flex h-full w-full min-h-0 min-w-0 p-0 md:p-3"
      style={{
        // navbarHeight includes the navbar's own bottom padding (the gap other
        // pages keep below the navbar); the agent cards drop most of it and sit
        // just 2px under the navbar row.
        paddingTop: `calc(${String(navbarHeight)}px - var(--navbar-pb) + 2px)`,
      }}
    >
      <ResizablePanelGroup
        orientation="horizontal"
        className="flex h-full w-full gap-1"
        defaultLayout={defaultLayout}
        onLayoutChanged={onLayoutChanged}
      >
        <ResizablePanel
          id={DASHBOARD_PANEL_ID}
          defaultSize="33%"
          minSize="300px"
        >
          <div className="h-full">
            <Dashboard fullscreen={false} />
          </div>
        </ResizablePanel>

        {!chatCollapsed && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel
              id={CHAT_PANEL_ID}
              defaultSize="67%"
              minSize="320px"
            >
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
