import * as React from "react"

import type { DashboardConfig, PageConfig } from "@/config"
import { NavMain } from "@/components/nav-main"
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"

export function AppSidebar({
  config,
  pages,
  onReorder,
  activePageId,
  onNavigate,
  ...props
}: {
  config: DashboardConfig
  pages: PageConfig[]
  onReorder: (pages: PageConfig[]) => void
  activePageId: string
  onNavigate: (id: string) => void
} & React.ComponentProps<typeof Sidebar>) {
  const navItems = pages.map((p) => ({
    id: p.id,
    title: p.title,
    icon: p.icon,
  }))

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="flex items-center gap-2 overflow-hidden px-3 py-2 transition-[padding] duration-200 ease-linear group-data-[collapsible=icon]:px-0">
              <div className="flex aspect-square size-8 shrink-0 items-center justify-center rounded-full">
                {config.titleIcon}
              </div>
              <span className="truncate font-heading font-medium">{config.title}</span>
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={navItems}
          activeId={activePageId}
          onNavigate={onNavigate}
          onReorder={(reordered) => {
            const idOrder = reordered.map((item) => item.id)
            onReorder(idOrder.map((id) => pages.find((p) => p.id === id)!))
          }}
        />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
