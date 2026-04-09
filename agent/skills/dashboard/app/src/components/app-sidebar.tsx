import * as React from "react"

import type { DashboardConfig } from "@/config"
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
  activePageId,
  onNavigate,
  ...props
}: {
  config: DashboardConfig
  activePageId: string
  onNavigate: (id: string) => void
} & React.ComponentProps<typeof Sidebar>) {
  const navItems = config.pages.map((p) => ({
    id: p.id,
    title: p.title,
    icon: p.icon,
  }))

  return (
    <Sidebar collapsible="icon" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <div className="flex items-center gap-2 p-1.5">
              {config.titleIcon}
              <span className="text-base font-heading font-medium group-data-[collapsible=icon]:hidden">
                {config.title}
              </span>
            </div>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={navItems}
          activeId={activePageId}
          onNavigate={onNavigate}
        />
      </SidebarContent>
      <SidebarRail />
    </Sidebar>
  )
}
