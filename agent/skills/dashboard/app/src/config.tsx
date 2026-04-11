// ============================================================================
// Dashboard Configuration
// Edit this file to customize the sidebar navigation and page content.
// Each page entry adds a sidebar nav item and maps to a React component.
//
// To add a page:
//   1. Create a component in src/pages/ (e.g. src/pages/analytics.tsx)
//   2. Import it here and add an entry to the `pages` array
//   3. Rebuild: cd app && npx vite build
// ============================================================================

import type { ComponentType, ReactNode } from "react"
import { LayoutDashboardIcon } from "lucide-react"

// --- Types ---

export interface PageConfig {
  id: string
  title: string
  icon: ReactNode
  component: ComponentType
}

export interface DashboardConfig {
  title: string
  titleIcon: ReactNode
  pages: PageConfig[]
}

// --- Configuration ---

export const config: DashboardConfig = {
  title: "Dashboard",
  titleIcon: <LayoutDashboardIcon className="size-5!" />,

  pages: [
    // Add pages here:
  ],
}
