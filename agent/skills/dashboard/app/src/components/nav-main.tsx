import type { ReactNode } from "react"
import { Reorder } from "motion/react"
import { ChevronRightIcon } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  SidebarGroup,
  SidebarMenuButton,
  SidebarMenuSub,
  SidebarMenuSubButton,
  SidebarMenuSubItem,
  useSidebar,
} from "@/components/ui/sidebar"
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip"

export type NavItem = {
  id: string
  title: string
  icon?: ReactNode
  children?: NavItem[]
}

export function NavMain({
  items,
  activeId,
  onNavigate,
  onReorder,
}: {
  items: NavItem[]
  activeId: string
  onNavigate: (id: string) => void
  onReorder: (items: NavItem[]) => void
}) {
  return (
    <SidebarGroup>
      <Reorder.Group
        axis="y"
        values={items.map((i) => i.id)}
        onReorder={(ids) => {
          const lookup = new Map(items.map((i) => [i.id, i]))
          onReorder(ids.map((id) => lookup.get(id)!))
        }}
        data-slot="sidebar-menu"
        data-sidebar="menu"
        className="flex w-full min-w-0 flex-col gap-0.5"
      >
        {items.map((item) =>
          item.children?.length ? (
            <CollapsibleNavItem
              key={item.id}
              item={item}
              activeId={activeId}
              onNavigate={onNavigate}
            />
          ) : (
            <Reorder.Item
              key={item.id}
              value={item.id}
              data-slot="sidebar-menu-item"
              data-sidebar="menu-item"
              className="group/menu-item relative rounded-xl"
              style={{ background: "transparent" }}
              whileDrag={{ scale: 1.03, background: "var(--sidebar)", boxShadow: "0 4px 12px rgba(0,0,0,.1)" }}
              transition={{ duration: 0.15 }}
            >
              <SidebarMenuButton
                tooltip={item.title}
                isActive={item.id === activeId}
                onClick={() => onNavigate(item.id)}
              >
                {item.icon}
                <span>{item.title}</span>
              </SidebarMenuButton>
            </Reorder.Item>
          ),
        )}
      </Reorder.Group>
    </SidebarGroup>
  )
}

function CollapsibleNavItem({
  item,
  activeId,
  onNavigate,
}: {
  item: NavItem
  activeId: string
  onNavigate: (id: string) => void
}) {
  const { state, isMobile } = useSidebar()
  const collapsed = state === "collapsed" && !isMobile
  const hasActiveChild = item.children?.some((c) => c.id === activeId) ?? false

  return (
    <Reorder.Item
      key={item.id}
      value={item.id}
      data-slot="sidebar-menu-item"
      data-sidebar="menu-item"
      className="group/menu-item relative rounded-xl"
      style={{ background: "transparent" }}
      whileDrag={{ scale: 1.03, background: "var(--sidebar)", boxShadow: "0 4px 12px rgba(0,0,0,.1)" }}
      transition={{ duration: 0.15 }}
    >
      <Collapsible defaultOpen={hasActiveChild} className="group/collapsible">
        <div className="rounded-lg [[data-collapsible=icon]_&]:rounded-xl [[data-collapsible=icon]_&]:group-data-[state=open]/collapsible:ring-1 [[data-collapsible=icon]_&]:group-data-[state=open]/collapsible:ring-sidebar-border [[data-collapsible=icon]_&]:group-data-[state=open]/collapsible:my-1">
          <CollapsibleTrigger asChild>
            <SidebarMenuButton tooltip={item.title} className="transition-colors duration-0 group-data-[state=open]/collapsible:duration-200 [[data-collapsible=icon]_&]:group-data-[state=open]/collapsible:bg-primary/40 [[data-collapsible=icon]_&]:group-data-[state=open]/collapsible:hover:bg-primary/45">
              {item.icon}
              <span>{item.title}</span>
              <ChevronRightIcon className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90 group-data-[collapsible=icon]:hidden" />
            </SidebarMenuButton>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <SidebarMenuSub>
              {item.children!.map((child) => (
                <SidebarMenuSubItem key={child.id}>
                  {collapsed ? (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <SidebarMenuSubButton
                          isActive={child.id === activeId}
                          onClick={() => onNavigate(child.id)}
                        >
                          {child.icon}
                          <span>{child.title}</span>
                        </SidebarMenuSubButton>
                      </TooltipTrigger>
                      <TooltipContent side="right" align="center">
                        {child.title}
                      </TooltipContent>
                    </Tooltip>
                  ) : (
                    <SidebarMenuSubButton
                      isActive={child.id === activeId}
                      onClick={() => onNavigate(child.id)}
                    >
                      {child.icon}
                      <span>{child.title}</span>
                    </SidebarMenuSubButton>
                  )}
                </SidebarMenuSubItem>
              ))}
            </SidebarMenuSub>
          </CollapsibleContent>
        </div>
      </Collapsible>
    </Reorder.Item>
  )
}
