import type { ReactNode } from "react"
import { SidebarTrigger } from "@/components/ui/sidebar"

export function SiteHeader({ title, icon }: { title: string; icon?: ReactNode }) {
  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-2 border-b transition-[width,height] ease-linear group-has-data-[collapsible=icon]/sidebar-wrapper:h-(--header-height)">
      <div className="flex w-full min-w-0 items-center gap-2 px-4 lg:px-6">
        <SidebarTrigger className="-ml-1 shrink-0" />
        <div className="flex min-w-0 items-center gap-2">
          {icon ? (
            <span className="flex shrink-0 [&_svg]:size-4 [&_svg]:shrink-0">
              {icon}
            </span>
          ) : null}
          <h1 className="truncate text-base font-medium">{title}</h1>
        </div>
      </div>
    </header>
  )
}
