import { useState, useEffect } from "react"
import { LayoutDashboard } from "lucide-react"
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar"
import { TooltipProvider } from "@/components/ui/tooltip"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty"
import { AppSidebar } from "@/components/app-sidebar"
import { SiteHeader } from "@/components/site-header"
import { config } from "./config"
import {
  isFullscreen as getFullscreen,
  onLayoutChange,
} from "./lib/parent-bridge"

// --- Empty state toggle ---
// Set to false once there are configured pages in config.tsx.
const SHOW_EMPTY_STATE = true

export default function App() {
  const [fullscreen, setFullscreen] = useState(getFullscreen)
  const [activePageId, setActivePageId] = useState(config.pages[0]?.id ?? "")
  const activePage =
    config.pages.find((p) => p.id === activePageId) ?? config.pages[0]

  useEffect(() => onLayoutChange(setFullscreen), [])

  if (SHOW_EMPTY_STATE) {
    return (
      <Empty className="flex-1 h-full w-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LayoutDashboard />
          </EmptyMedia>
          <EmptyTitle>your dashboard</EmptyTitle>
          <EmptyDescription>
            ask your agent to set up the dashboard and add some widgets
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <TooltipProvider>
      <SidebarProvider
        style={
          {
            "--sidebar-width": "calc(var(--spacing) * 72)",
            "--header-height": "calc(var(--spacing) * 12)",
          } as React.CSSProperties
        }
      >
        <AppSidebar
          config={config}
          activePageId={activePageId}
          onNavigate={setActivePageId}
          variant="inset"
        />
        <SidebarInset>
          <SiteHeader title={activePage?.title ?? ""} />
          <div className={`flex flex-1 flex-col ${fullscreen ? "px-page" : ""}`}>
            <div className="@container/main flex flex-1 flex-col gap-2">
              {activePage && <activePage.component />}
            </div>
          </div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}
