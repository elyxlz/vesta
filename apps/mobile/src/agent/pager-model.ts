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

export interface PagerAnimationRanges {
  input: number[];
  selection: number[];
  visibility: number[];
}

export function getPagerAnimationRanges(
  pageCount: number,
): PagerAnimationRanges {
  const count = Math.max(2, Math.floor(pageCount));
  const input = [0];
  const selection = [0];
  const visibility = [0];

  for (let page = 0; page < count - 1; page += 1) {
    input.push((page * 100 + 16) / 100, (page * 100 + 84) / 100, page + 1);
    selection.push(page, page + 1, page + 1);
    visibility.push(1, 1, 0);
  }

  return { input, selection, visibility };
}
