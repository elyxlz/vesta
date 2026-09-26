import type { NavLayout } from "@/hooks/use-nav-layout";

export type PageSwitch = "dashboard" | "chat" | null;

// Which page the top bar offers beside home. A touch window switches from the
// bottom tab bar instead; a wide window shows the dashboard with the chat as a
// side panel, so only the full-screen chat offers the way back.
export function pageSwitchFor(
  layout: NavLayout,
  page: { onDashboard: boolean; onChat: boolean },
): PageSwitch {
  if (layout === "touch-narrow") return null;
  if (page.onChat) return "dashboard";
  if (layout === "mouse-narrow" && page.onDashboard) return "chat";
  return null;
}
