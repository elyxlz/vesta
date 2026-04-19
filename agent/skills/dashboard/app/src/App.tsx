import { useEffect, useMemo, useState } from "react"
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
import { Shell, useShellRef } from "@/components/shell"
import { SiteHeader } from "@/components/site-header"
import { getAgentName, waitForAuth } from "@/lib/parent-bridge"
import { config, type PageConfig } from "./config"

const AGENT_PAGE_ID = "agent"

/** Replace the "Agent" page title with "Agent <agentName>" once the bridge reveals the name. */
function applyAgentName(pages: PageConfig[], agentName: string | null): PageConfig[] {
  if (!agentName) return pages
  const titled = agentName.charAt(0).toUpperCase() + agentName.slice(1)
  return pages.map((p) => {
    if (p.id === AGENT_PAGE_ID) return { ...p, title: `Agent ${titled}` }
    if (p.children) return { ...p, children: applyAgentName(p.children, agentName) }
    return p
  })
}

const SHOW_EMPTY_STATE = config.pages.length === 0
const STORAGE_KEY = "vesta-dashboard-page-order"
const ACTIVE_PAGE_KEY = "vesta-dashboard-active-page"
const IDLE_RESET_PAGE_ID = "agent"
const IDLE_RESET_MS = 5 * 60 * 1000 // 5 min of no user interaction → jump back to agent page

function findPage(pages: PageConfig[], id: string): PageConfig | undefined {
  for (const p of pages) {
    if (p.id === id) return p
    if (p.children) {
      const found = findPage(p.children, id)
      if (found) return found
    }
  }
  return undefined
}

function firstNavigablePage(pages: PageConfig[]): string {
  for (const p of pages) {
    if (p.component) return p.id
    if (p.children) {
      const id = firstNavigablePage(p.children)
      if (id) return id
    }
  }
  return ""
}

function hasPage(pages: PageConfig[], id: string): boolean {
  return findPage(pages, id) !== undefined
}

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
  if (saved && hasPage(pages, saved)) return saved
  return firstNavigablePage(pages)
}

function DashboardContent({ agentName }: { agentName: string | null }) {
  const shellRef = useShellRef()
  const [rawPages, setRawPages] = useState(loadPageOrder)
  const pages = useMemo(() => applyAgentName(rawPages, agentName), [rawPages, agentName])
  const [activePageId, setActivePageId] = useState(() => loadActivePage(pages))
  const activePage = findPage(pages, activePageId)

  // Idle reset: after IDLE_RESET_MS of no user interaction, navigate to the agent page.
  useEffect(() => {
    if (!hasPage(pages, IDLE_RESET_PAGE_ID)) return
    let timer: number | undefined
    const reset = () => {
      if (timer !== undefined) window.clearTimeout(timer)
      timer = window.setTimeout(() => {
        setActivePageId((current) => {
          if (current === IDLE_RESET_PAGE_ID) return current
          localStorage.setItem(ACTIVE_PAGE_KEY, IDLE_RESET_PAGE_ID)
          return IDLE_RESET_PAGE_ID
        })
      }, IDLE_RESET_MS)
    }
    const events: (keyof WindowEventMap)[] = ["mousemove", "mousedown", "keydown", "touchstart", "scroll", "wheel"]
    events.forEach((e) => window.addEventListener(e, reset, { passive: true }))
    reset()
    return () => {
      if (timer !== undefined) window.clearTimeout(timer)
      events.forEach((e) => window.removeEventListener(e, reset))
    }
  }, [pages])

  return (
    <TooltipProvider>
      <SidebarProvider
        container={shellRef.current}
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
            setRawPages(reordered)
            localStorage.setItem(STORAGE_KEY, JSON.stringify(reordered.map((p) => p.id)))
          }}
          activePageId={activePageId}
          onNavigate={(id) => {
            setActivePageId(id)
            localStorage.setItem(ACTIVE_PAGE_KEY, id)
          }}
        />
        <SidebarInset>
          <SiteHeader title={activePage?.title ?? ""} icon={activePage?.icon} />
          <div className="@container/main overflow-y-auto flex-1 min-h-0 px-4 py-4 lg:px-6">
            {activePage?.component && <activePage.component />}
          </div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  )
}

export default function App() {
  const [agentName, setAgentName] = useState(getAgentName)

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
    <Shell>
      <DashboardContent agentName={agentName} />
    </Shell>
  )
}
