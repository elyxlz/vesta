import { useEffect, useState } from "react"
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
import { Shell } from "@/components/shell"
import { SiteHeader } from "@/components/site-header"
import { getAgentName, waitForAuth } from "@/lib/parent-bridge"
import { config, type PageConfig } from "./config"

const SHOW_EMPTY_STATE = config.pages.length === 0
const STORAGE_KEY = "vesta-dashboard-page-order"
const ACTIVE_PAGE_KEY = "vesta-dashboard-active-page"

function loadPageOrder(): PageConfig[] {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (!saved) return config.pages
    const ids: string[] = JSON.parse(saved)
    const lookup = new Map(config.pages.map((p) => [p.id, p]))
    const ordered = ids.filter((id) => lookup.has(id)).map((id) => lookup.get(id)!)
    const newPages = config.pages.filter((p) => !ids.includes(p.id))
    return [...newPages, ...ordered]
  } catch {
    return config.pages
  }
}

function loadActivePage(pages: PageConfig[]): string {
  const saved = localStorage.getItem(ACTIVE_PAGE_KEY)
  if (saved && pages.some((p) => p.id === saved)) return saved
  return pages[0]?.id ?? ""
}

export default function App() {
  const [pages, setPages] = useState(loadPageOrder)
  const [activePageId, setActivePageId] = useState(() => loadActivePage(pages))
  const [agentName, setAgentName] = useState(getAgentName)
  const activePage =
    pages.find((p) => p.id === activePageId) ?? pages[0]

  useEffect(() => {
    waitForAuth().then(() => setAgentName(getAgentName()))
  }, [])

  if (SHOW_EMPTY_STATE) {
    return (
      <Shell>
        <Empty className="flex-1 h-full w-full border-0">
          <EmptyHeader>
            <EmptyMedia variant="icon" className="size-12 rounded-full bg-sidebar-primary text-sidebar-primary-foreground [&_svg:not([class*='size-'])]:size-6">
              {config.titleIcon}
            </EmptyMedia>
            <EmptyTitle>your dashboard</EmptyTitle>
            <EmptyDescription>
              ask {agentName ?? "your agent"} to set up the dashboard and add some widgets
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      </Shell>
    )
  }

  return (
    <Shell className="m-2 h-[calc(100%-1rem)] w-[calc(100%-1rem)]">
      <TooltipProvider>
        <SidebarProvider
          style={
            {
              "--sidebar-width": "calc(var(--spacing) * 52)",
              "--header-height": "calc(var(--spacing) * 12)",
            } as React.CSSProperties
          }
        >
          <AppSidebar
            config={config}
            pages={pages}
            onReorder={(reordered) => {
              setPages(reordered)
              localStorage.setItem(STORAGE_KEY, JSON.stringify(reordered.map((p) => p.id)))
            }}
            activePageId={activePageId}
            onNavigate={(id) => {
              setActivePageId(id)
              localStorage.setItem(ACTIVE_PAGE_KEY, id)
            }}
          />
          <SidebarInset>
            <SiteHeader title={activePage?.title ?? ""} />
            <div className="@container/main overflow-y-auto flex-1 min-h-0 px-4 py-4 lg:px-6">
              {activePage && <activePage.component />}
            </div>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </Shell>
  )
}
