import { Reorder } from "motion/react"
import {
  SidebarGroup,
  SidebarMenuButton,
} from "@/components/ui/sidebar"

type NavItem = {
  id: string
  title: string
  icon?: React.ReactNode
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
        {items.map((item) => (
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
        ))}
      </Reorder.Group>
    </SidebarGroup>
  )
}
