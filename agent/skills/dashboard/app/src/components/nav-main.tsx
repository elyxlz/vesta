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
} from "@/components/ui/sidebar"

export type NavItem = {
  id: string
  title: string
  icon?: React.ReactNode
  hasComponent?: boolean
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
              hasComponent={!!item.hasComponent}
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
  hasComponent,
}: {
  item: NavItem
  activeId: string
  onNavigate: (id: string) => void
  hasComponent: boolean
}) {
  const isParentActive = item.id === activeId
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
      <Collapsible defaultOpen={hasActiveChild || isParentActive} className="group/collapsible">
        {hasComponent ? (
          <div className="flex items-center">
            <SidebarMenuButton
              tooltip={item.title}
              isActive={isParentActive}
              onClick={() => onNavigate(item.id)}
              className="flex-1"
            >
              {item.icon}
              <span>{item.title}</span>
            </SidebarMenuButton>
            <CollapsibleTrigger asChild>
              <button className="flex items-center justify-center size-8 shrink-0 rounded-xl text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer">
                <ChevronRightIcon className="size-4 transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
              </button>
            </CollapsibleTrigger>
          </div>
        ) : (
          <CollapsibleTrigger asChild>
            <SidebarMenuButton tooltip={item.title}>
              {item.icon}
              <span>{item.title}</span>
              <ChevronRightIcon className="ml-auto transition-transform duration-200 group-data-[state=open]/collapsible:rotate-90" />
            </SidebarMenuButton>
          </CollapsibleTrigger>
        )}
        <CollapsibleContent>
          <SidebarMenuSub>
            {item.children!.map((child) => (
              <SidebarMenuSubItem key={child.id}>
                <SidebarMenuSubButton
                  isActive={child.id === activeId}
                  onClick={() => onNavigate(child.id)}
                >
                  <span>{child.title}</span>
                </SidebarMenuSubButton>
              </SidebarMenuSubItem>
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </Collapsible>
    </Reorder.Item>
  )
}
