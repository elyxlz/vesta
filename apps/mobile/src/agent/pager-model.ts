export type AgentPageKey = "chat" | "dashboard" | "notifications" | "logs";

export interface AgentPagePreferences {
  showChatPage: boolean;
  showDashboardPage: boolean;
  showNotificationsPage: boolean;
  showLogsPage: boolean;
}

// Every page is optional; with all of them off the pager still needs one page, so chat stays.
export function getAgentPageKeys({
  showChatPage,
  showDashboardPage,
  showNotificationsPage,
  showLogsPage,
}: AgentPagePreferences): AgentPageKey[] {
  const pages: AgentPageKey[] = [
    ...(showChatPage ? (["chat"] as const) : []),
    ...(showDashboardPage ? (["dashboard"] as const) : []),
    ...(showNotificationsPage ? (["notifications"] as const) : []),
    ...(showLogsPage ? (["logs"] as const) : []),
  ];
  return pages.length > 0 ? pages : ["chat"];
}
