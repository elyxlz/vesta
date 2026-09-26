export type PageSwitch = "dashboard" | "chat" | null;

// Which page the top bar offers beside home. A touch-sized window switches
// from the bottom tab bar instead; a wide window shows the dashboard with the
// chat as a side panel, so only the full-screen chat offers the way back.
export function pageSwitchFor({
  bottomNav,
  narrow,
  onDashboard,
  onChat,
}: {
  bottomNav: boolean;
  narrow: boolean;
  onDashboard: boolean;
  onChat: boolean;
}): PageSwitch {
  if (bottomNav) return null;
  if (onChat) return "dashboard";
  if (narrow && onDashboard) return "chat";
  return null;
}
