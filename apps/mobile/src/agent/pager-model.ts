export type AgentPageKey = "chat" | "dashboard" | "notifications" | "logs";

export interface AgentPagePreferences {
  showNotificationsPage: boolean;
  showLogsPage: boolean;
}

export function getAgentPageKeys({
  showNotificationsPage,
  showLogsPage,
}: AgentPagePreferences): AgentPageKey[] {
  return [
    "chat",
    "dashboard",
    ...(showNotificationsPage ? (["notifications"] as const) : []),
    ...(showLogsPage ? (["logs"] as const) : []),
  ];
}
