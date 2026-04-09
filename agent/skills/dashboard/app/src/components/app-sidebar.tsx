import * as React from "react"

import type { DashboardConfig } from "@/config"
import { NavMain } from "@/components/nav-main"
import { NavSecondary } from "@/components/nav-secondary"
import {
  Sidebar,
  SidebarContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
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
    <Sidebar collapsible="offcanvas" {...props}>
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton
              asChild
              className="data-[slot=sidebar-menu-button]:p-1.5!"
            >
              <a href="#">
                {config.titleIcon}
                <span className="text-base font-semibold">{config.title}</span>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <NavMain
          items={navItems}
          activeId={activePageId}
          onNavigate={onNavigate}
        />
        {config.secondaryNav && config.secondaryNav.length > 0 && (
          <NavSecondary items={config.secondaryNav} className="mt-auto" />
        )}
      </SidebarContent>
    </Sidebar>
  )
}
