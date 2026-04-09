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
    <div className={`h-full w-full ${fullscreen ? "p-page" : "pl-2 pr-4 py-4"}`}>
      <TooltipProvider>
        <SidebarProvider
          className="rounded-4xl bg-card shadow-md ring-1 ring-foreground/5 dark:ring-foreground/10 overflow-hidden h-full"
          style={
            {
              "--sidebar-width": "calc(var(--spacing) * 52)",
              "--header-height": "calc(var(--spacing) * 12)",
            } as React.CSSProperties
          }
        >
          <AppSidebar
            config={config}
            activePageId={activePageId}
            onNavigate={setActivePageId}
          />
          <SidebarInset>
            <SiteHeader title={activePage?.title ?? ""} />
            <div className="overflow-y-auto flex-1">
              {activePage && <activePage.component />}
            </div>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </div>
  )
}
