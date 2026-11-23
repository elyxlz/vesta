export type AgentPageKey = "chat" | "dashboard" | "notifications" | "logs";

export interface AgentPagePreferences {
  showDashboardPage: boolean;
  showNotificationsPage: boolean;
  showLogsPage: boolean;
}

// Chat is always the first page; the other pages are optional.
export function getAgentPageKeys({
  showDashboardPage,
  showNotificationsPage,
  showLogsPage,
}: AgentPagePreferences): AgentPageKey[] {
  return [
    "chat",
    ...(showDashboardPage ? (["dashboard"] as const) : []),
    ...(showNotificationsPage ? (["notifications"] as const) : []),
    ...(showLogsPage ? (["logs"] as const) : []),
  ];
}
